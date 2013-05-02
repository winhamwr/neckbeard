import logging
import time

import boto.exception
import dateutil.parser
import requests
from boto.ec2 import elb
from requests.exceptions import (
    ConnectionError,
    Timeout,
    RequestException,
)
from simpledb import models

from neckbeard.output import fab_out_opts

NODE_AWS_TYPES = ['ec2', 'rds', 'elb']
EC2_RETIRED_STATES = ['shutting-down', 'terminated']
RDS_RETIRED_STATES = ['deleted']

logger = logging.getLogger('cloud_resource')

fab_output_hides = fab_out_opts[logger.getEffectiveLevel()]
fab_quiet = fab_output_hides + ['stderr']

# This is just a non-functional place to track configuration options to provide
# a starting point once we add actual validation
REQUIRED_CONFIGURATION = {
    'ec2': [
        'aws.keypair',
    ],
}
OPTIONAL_CONFIGURATION = {
    'ec2': [
        'aws.elastic_ip',
    ],
}


class InfrastructureNode(models.Model):
    nodename = models.ItemName()
    generation_id = models.NumberField(required=True)
    # The environment name. Eg. test, beta, staging, live
    deployment_name = models.Field(required=True)
    # Type of node. Eg. ec2, rds, elb
    aws_type = models.Field(required=True)
    # Unique AWS id. Eg. `i-xxxxxx`
    aws_id = models.Field(required=True)
    # Unique ID within this generation of a deployment
    # This determine which configuration is pulled
    name = models.Field(required=True)
    creation_date = models.DateTimeField(required=True)
    is_running = models.NumberField(default=1, required=True)
    # Is this generation the currently-active generation
    is_active_generation = models.NumberField(default=0, required=True)
    # Whether or not we've completed the first deploy on this node
    # Used to allow the first deploy to differ from subsequent deploys
    # for one-time operations per node. Idempotency is preferred, but this is a
    # shortcut towards some speed improvements. We only need to do EBS volume
    # mounting on the first run, for example.
    initial_deploy_complete = models.NumberField(default=0, required=True)

    def __init__(self, *args, **kwargs):
        self.ec2conn = None
        self.rdsconn = None
        self.elbconn = None
        self._boto_instance = None
        self._deployment_info = None
        super(InfrastructureNode, self).__init__(*args, **kwargs)

    def __str__(self):
        if self.aws_type in NODE_AWS_TYPES:
            output_str = '%s:%s[%s]<%s>' % (
                self.aws_type,
                self.name,
                self.aws_id,
                self.creation_date,
            )
            return output_str

        return super(InfrastructureNode, self).__str__()

    def get_status_output(self):
        """
        Provide a detailed string representation of the instance with its
        current operational/health status.
        """
        if self.aws_type in NODE_AWS_TYPES:
            status_str = ''
            if not self.is_running:
                status_str += 'RETIRED-'
            else:
                if self.is_operational:
                    status_str += 'UP-'
                else:
                    status_str += 'INACTIVE-'
                if not self.is_healthy:
                    status_str += 'UNHEALTHY-'

            return "%s-%s" % (status_str, self)

        return "UNKNOWN-%s" % self

    def set_aws_conns(self, ec2conn, rdsconn):
        self.ec2conn = ec2conn
        self.rdsconn = rdsconn

    def set_deployment_info(self, deployment_info):
        self._deployment_info = deployment_info

    def is_actually_running(self):
        """
        Checks AWS to ensure this node hasn't been terminated.
        """
        if self.aws_type == 'ec2':
            if self.boto_instance:
                if self.boto_instance.state not in EC2_RETIRED_STATES:
                    return True
        elif self.aws_type == 'rds':
            if self.boto_instance:
                if self.boto_instance.status not in RDS_RETIRED_STATES:
                    return True

        return False

    def terminate(self):
        if (self.is_active_generation and self.is_operational):
            raise Exception("Can't hard-terminate an active, operational node")

        if self.aws_type == 'ec2':
            if self.is_actually_running():
                self.boto_instance.terminate()
        elif self.aws_type == 'rds':
            if self.is_actually_running():
                final_snapshot = self._deployment_info.get(
                    'final_snapshot',
                    None,
                )
                if final_snapshot:
                    self.boto_instance.stop(
                        skip_final_snapshot=False,
                        final_snapshot_id=final_snapshot,
                    )
                else:
                    self.boto_instance.stop(
                        skip_final_snapshot=True, final_snapshot_id=None)

        self.is_running = 0
        self.save()

    def retire(self):
        """
        Mark this node as retired and no longer used. Useful for hung nodes.
        """
        if (self.is_active_generation and self.is_operational):
            raise Exception("Can't retire an active, operational node")

        self.is_running = 0
        self.save()

    def make_temporarily_inoperative(self):
        """
        Make the given node temporarily inoperative in preperation for putting
        it back in to operation shortly after.

        This is the call to use for things like rotating in and out of the
        loadbalancer. ``make_fully_inoperative`` should be used for planned
        long-term inoperability.
        """
        if self.aws_type == 'ec2':
            self._remove_from_loadbalancer()
        elif self.aws_type == 'rds':
            pass

    def _remove_from_loadbalancer(self):
        """
        If this node is in a loadbalancer, remove it from that loadbalancer.
        """
        if self.aws_type != 'ec2':
            return

        loadbalancer = self.get_loadbalancer()
        if not loadbalancer:
            return

        # Check if this instance is even in the load balancer
        if not self._instance_in_load_balancer():
            logger.debug(
                "_remove_from_loadbalancer: Instance %s not in loadbalancer",
                self.boto_instance,
            )
            return

        logger.info(
            "Removing node from loadbalancer: %s",
            loadbalancer,
        )
        loadbalancer.deregister_instances([self.aws_id])

    def make_fully_inoperative(self):
        """
        Make the given node fully inoperative. This is the call to use for
        planned long-term inoperability. ``make_temporarily_inoperative``
        is more useful for temporary inoperability (such as rotating in
        and out of the loadbalancer).
        """
        if self.aws_type == 'ec2':
            elastic_ip = self.get_elastic_ip()

            if elastic_ip and elastic_ip.instance_id:
                if elastic_ip.instance_id == self.boto_instance.id:
                    logger.info(
                        "Dissociating elastic IP %s from instance %s",
                        elastic_ip,
                        elastic_ip.instance_id,
                    )
                    self.ec2conn.disassociate_address(elastic_ip.public_ip)

            self._remove_from_loadbalancer()
        elif self.aws_type == 'rds':
            pass

    def refresh_boto_instance(self):
        self._boto_instance = None

    @property
    def boto_instance(self):
        if not self._boto_instance:
            if self.aws_type == 'ec2':
                reservations = self.ec2conn.get_all_instances(
                    instance_ids=[self.aws_id])
                if len(reservations) == 1:
                    self._boto_instance = reservations[0].instances[0]
            elif self.aws_type == 'rds':
                try:
                    db_instances = self.rdsconn.get_all_dbinstances(
                        instance_id=self.aws_id)
                except boto.exception.BotoServerError:
                    return self._boto_instance
                if len(db_instances) == 1:
                    self._boto_instance = db_instances[0]

        return self._boto_instance

    @property
    def launch_time(self):
        if not self.boto_instance:
            return None

        if self.aws_type == 'ec2':
            return dateutil.parser.parse(self.boto_instance.launch_time)
        elif self.aws_type == 'rds':
            return dateutil.parser.parse(self.boto_instance.create_time)

    def _instance_in_load_balancer(self):
        """
        Determine if this instance is in its current loadbalancer.
        """
        loadbalancer = self.get_loadbalancer()
        if self.boto_instance is None:
            return False

        if loadbalancer is None:
            return False

        # The comparator between instances do not necessarily work, compare by
        # id instead.
        ids_in_lb = [i.id for i in loadbalancer.instances]
        return self.boto_instance.id in ids_in_lb

    @property
    def is_operational(self):
        """
        Is this instance fully operational as defined by the deployment info.

        ie. is it in the loadbalancer with the correct ip or is it active with
        no pending rds config values
        """
        if not self.boto_instance:
            return False

        if not self._deployment_info:
            logger.critical(
                "No deployment configuration found for node: %s",
                self,
            )
            logger.critical(
                "Unable to determine operational status. "
                "Assuming NOT operational."
            )
            return False

        if self.aws_type == 'ec2':
            key_name = self._deployment_info['aws']['keypair']
            elastic_ip = self.get_elastic_ip()
            loadbalancer = self.get_loadbalancer()

            if self.boto_instance.state != 'running':
                logger.debug(
                    "is_operational: Instance %s not running",
                    self.boto_instance,
                )
                return False
            if self.boto_instance.key_name != key_name:
                logger.debug(
                    "is_operational: Instance %s has wrong key",
                    self.boto_instance,
                )
                return False
            if elastic_ip:
                if self.boto_instance.id != elastic_ip.instance_id:
                    logger.debug(
                        "is_operational: Instance %s has wrong elastic ip",
                        self.boto_instance,
                    )
                    return False
            if loadbalancer:
                if not self._instance_in_load_balancer():
                    logger.debug(
                        "is_operational: Instance %s not in loadbalancer",
                        self.boto_instance,
                    )
                    logger.debug(
                        'Instances in loadbalancer: %s',
                        loadbalancer.instances,
                    )
                    return False

                health_list = loadbalancer.get_instance_health(
                    instances=[self.aws_id])
                assert len(health_list) == 1
                if health_list[0].state != 'InService':
                    logger.debug(
                        "is_operational: Node %s not healthy in loadbalancer.",
                        self.boto_instance,
                    )
                    logger.debug("LB health state: %s", health_list[0].state)
                    return False

            return True
        elif self.aws_type == 'rds':
            if self.boto_instance.status != 'available':
                logger.debug(
                    "is_operational: Instance %s not available",
                    self.boto_instance,
                )
                return False
            # TODO: add checks for pending values and matching params

            return True

        return False

    def get_health_check_url(self):
        if 'health_check' not in self._deployment_info:
            return None
        if not self.boto_instance.public_dns_name:
            logger.debug(
                "No health check url due to no public dns name",
            )
            return None

        health_check = self._deployment_info['health_check']
        status_url = health_check['status_url']

        status_url = 'http://%s%s' % (
            self.boto_instance.public_dns_name,
            status_url,
        )

        return status_url

    def passes_health_check(self):
        """
        Does this node currently pass the `health_check` as defined in its
        configuration.

        If no `health_check` is defined, returns True.
        """
        status_url = self.get_health_check_url()
        if not status_url:
            logger.info("No health check defined. Assuming healthy.")
            return True

        health_check = self._deployment_info['health_check']
        status_success_string = health_check['status_contains']
        timeout = health_check['status_check_timeout']

        try:
            site_status = requests.get(status_url, timeout=timeout)
        except ConnectionError:
            logger.info("health_check unavailable for %s", self)
            logger.debug("status url: %s", status_url)
            return False
        except Timeout:
            logger.info("health_check timed out for %s", self)
            logger.debug("status url: %s", status_url)
            return False
        except RequestException, e:
            logger.info("health_check raised exception for %s", self)
            logger.debug("status url: %s", status_url)
            logger.debug("Exception: %s", e)
            return False
        if status_success_string not in site_status.text:
            logger.debug(
                "Required string not present in health_check for %s",
                self,
            )
            logger.debug("status url: %s", status_url)
            logger.debug("Required string: %s", status_success_string)
            return False

        return True

    @property
    def is_healthy(self):
        """
        Is this instance healthy according to its status checks. Healthy nodes
        are ready to perform their function, regardles of whether or not
        they're currently in operation (in the Loadbalancer, with the proper
        IP, etc).
        """
        if not self.boto_instance:
            return False

        if not self._deployment_info:
            logger.critical(
                "No deployment configuration found for node: %s",
                self,
            )
            logger.critical(
                "Unable to determine health status. "
                "Assuming NOT healthy."
            )
            return False

        if self.aws_type == 'ec2':
            key_name = self._deployment_info['aws']['keypair']

            if self.boto_instance.state != 'running':
                logger.debug(
                    "is_healthy: Instance %s not running",
                    self.boto_instance,
                )
                return False
            elif self.boto_instance.key_name != key_name:
                logger.debug(
                    "is_healthy: Instance %s has wrong key",
                    self.boto_instance,
                )
                return False

            return self.passes_health_check()
        elif self.aws_type == 'rds':
            if self.boto_instance.status != 'available':
                logger.debug("Instance %s not available" % self.boto_instance)
                return False
            # TODO: Check to ensure no pending values and that params match

            return True

        return False

    def make_operational(self, force_operational=False):
        if not force_operational:
            if not self.is_healthy or not self.is_active_generation:
                raise Exception(
                    "Only health nodes in the active generation "
                    "can be made operational"
                )

        if self.aws_type == 'ec2':
            elastic_ip = self.get_elastic_ip()
            loadbalancer = self.get_loadbalancer()

            if elastic_ip and elastic_ip.instance_id:
                if elastic_ip.instance_id != self.boto_instance.id:
                    logger.info(
                        "Dissociating elastic IP %s from instance %s",
                        elastic_ip,
                        elastic_ip.instance_id,
                    )
                    self.ec2conn.disassociate_address(elastic_ip.public_ip)

            # Switch the elastic IP
            if elastic_ip and elastic_ip.instance_id != self.boto_instance.id:
                logger.info(
                    "Pointing IP %s to %s",
                    elastic_ip.public_ip,
                    self.boto_instance,
                )
                while elastic_ip.instance_id != self.boto_instance.id:
                    self.boto_instance.use_ip(elastic_ip)
                    elastic_ip = self.get_elastic_ip()
                    logger.info(
                        "Waiting 5s for ip %s to associated to %s",
                        elastic_ip,
                        self.boto_instance,
                    )
                    time.sleep(5)
                logger.info(
                    "IP %s succesfully associated to %s",
                    elastic_ip,
                    self.boto_instance,
                )

            # Stick the instance in the loadbalancer
            if loadbalancer:
                logger.info(
                    "Placing node <%s> in to loadbalancer <%s>",
                    self,
                    loadbalancer,
                )
                loadbalancer.register_instances([self.boto_instance.id])

        elif self.aws_type == 'rds':
            pass

    def get_loadbalancer(self):
        if not self.elbconn:
            self.elbconn = elb.ELBConnection(
                self.ec2conn.aws_access_key_id,
                self.ec2conn.aws_secret_access_key)

        if not self._deployment_info.get('loadbalancer', None):
            return None

        elb_list = self.elbconn.get_all_load_balancers(
            load_balancer_names=[self._deployment_info['loadbalancer']])
        assert len(elb_list) == 1

        return elb_list[0]

    def get_elastic_ip(self):
        configured_ip = self._deployment_info['aws'].get('elastic_ip')
        if not configured_ip:
            return None

        ips = self.ec2conn.get_all_addresses(
            [configured_ip],
        )
        assert len(ips) == 1

        return ips[0]

    def set_initial_deploy_complete(self):
        """
        Record that the initial deployment operation has completed
        succesfully.
        """
        self.initial_deploy_complete = 1
        self.save()

    def verify_running_state(self):
        if self.is_running == 1 and not self.is_actually_running():
            self.is_running = 0
            self.save()
