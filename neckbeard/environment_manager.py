import logging
import time
from copy import copy
from datetime import datetime

from boto import ec2, rds

from neckbeard.cloud_resource import InfrastructureNode

logger = logging.getLogger('environment_manager')

WAIT_TIME = 10
MAKE_OPERATIONAL_TIMEOUT = 4 * 60  # 4 minutes


class PstatRdsId(object):
    def __init__(self, pstat_instance, pstat_version, counter):
        self.pstat_instance = pstat_instance
        self.pstat_version = pstat_version
        self.counter = int(counter)

    def __str__(self):
        rds_tpl = u'%s-v-%s-db-%s'
        rds_args = (
            self.pstat_instance,
            self.pstat_version.replace('.', '-'),
            self.counter,
        )
        return rds_tpl % rds_args

    @staticmethod
    def from_string(id_str):
        """
        Create and return a PstatRdsId from a compliant rds_id.

        >>> rds_id = PstatRdsId('test', '10.9.0', 3)
        >>> id_str = str(rds_id)
        >>> new_rds_id = PstatRdsId(id_str)
        >>> rds_id == new_rds_id
        True
        """
        try:
            pstat_instance, tail = id_str.split('-v-')
            pstat_version, counter = tail.split('-db-')
            counter = int(counter)

            return PstatRdsId(pstat_instance, pstat_version, counter)
        except ValueError:
            pass

        return None


class WaitTimedOut(Exception):
    """Waiting for an operation to complete timed out"""
    pass


class MissingAWSCredentials(Exception):
    pass


class NonUniformAWSCredentials(Exception):
    pass


class Deployment(object):
    """
    Use configuration info to classify all currently running ec2 and RDS
    instances and group them by deployment generation.
    """
    def __init__(self, deployment_name, ec2_nodes, rds_nodes, elb_nodes):
        """
        ``deployment_name`` A string uniquely identifying a deployment.
        """
        self.deployment_name = deployment_name
        self.deployment_confs = {}
        self.deployment_confs['ec2'] = ec2_nodes
        self.deployment_confs['rds'] = rds_nodes
        self.deployment_confs['elb'] = elb_nodes

        aws_credentials = self._get_valid_aws_credentials(
            self.deployment_confs,
        )

        self._pending_gen_id = None
        self._active_gen_id = None

        self.ec2conn = ec2.EC2Connection(
            aws_credentials['access_key_id'],
            aws_credentials['secret_access_key'],
        )
        self.rdsconn = rds.RDSConnection(
            aws_credentials['access_key_id'],
            aws_credentials['secret_access_key'],
        )

    def _get_valid_aws_credentials(self, deployment_confs):
        # TODO: Instead of just ensuring that all of the resources use the same
        # credentials, actually manage multiple connection
        aws_credentials = {
            'access_key_id': None,
            'secret_access_key': None,
        }
        for aws_type, configs_of_type in deployment_confs.items():
            for name, resource_config in configs_of_type.items():
                aws_config = resource_config.get('aws')
                if aws_config is None:
                    raise MissingAWSCredentials(
                        "%s resource %s has no 'aws' configs" % (
                            aws_type,
                            name,
                        ),
                    )

                # Ensure that the keys exist and that they're not different
                # from those found on other resources
                for key in ['access_key_id', 'secret_access_key']:
                    value = aws_config.get(key)

                    if value is None:
                        raise MissingAWSCredentials(
                            "%s resource %s has no '%s' config" % (
                                aws_type,
                                name,
                                key,
                            ),
                        )
                    other_resource_value = aws_credentials.get(key)
                    if other_resource_value is not None:
                        if value != other_resource_value:
                            raise NonUniformAWSCredentials(
                                (
                                    "%s resource %s has no '%s' config "
                                    "different from previously seen"
                                ) % (
                                    aws_type,
                                    name,
                                    key,
                                ),
                            )
                    aws_credentials[key] = value

        return aws_credentials

    @property
    def active_gen_id(self):
        if self._active_gen_id:
            return self._active_gen_id

        active_nodes = InfrastructureNode.objects.filter(
            deployment_name=self.deployment_name,
            is_active_generation=1)
        if len(active_nodes) == 0:
            return None

        first_active_node = active_nodes[0]
        gen_id = first_active_node.generation_id
        for active_node in active_nodes:
            if active_node.generation_id != gen_id:
                err_str = (
                    "Inconsistent generation ids in simpledb. "
                    "%s:%s and %s:%s both marked active"
                )
                context = (
                    first_active_node.aws_id,
                    first_active_node.generation_id,
                    active_node.aws_id,
                    active_node.generation_id)
                raise Exception(err_str % context)

        self._active_gen_id = gen_id

        return self._active_gen_id

    @property
    def pending_gen_id(self):
        if self._pending_gen_id:
            return self._pending_gen_id

        if self.active_gen_id:
            self._pending_gen_id = self.active_gen_id + 1
            return self._pending_gen_id

        self._pending_gen_id = 1
        return self._pending_gen_id

    def get_blank_node(self, aws_type):
        node = InfrastructureNode()
        node.set_aws_conns(self.ec2conn, self.rdsconn)
        node.aws_type = aws_type

        return node

    def get_active_node(self, aws_type, node_name):
        if self.active_gen_id:
            return self.get_node(
                aws_type, node_name, self.active_gen_id, is_running=1)
        return None

    def get_pending_node(self, aws_type, node_name):
        return self.get_node(
            aws_type, node_name, self.pending_gen_id, is_running=1)

    def get_all_active_nodes(self, is_running=None):
        if self.active_gen_id:
            return self.get_all_nodes(
                self.active_gen_id, is_running=is_running)
        return []

    def get_all_pending_nodes(self, is_running=None):
        return self.get_all_nodes(self.pending_gen_id, is_running=is_running)

    def get_all_old_nodes(self, is_running=None):
        nodes = []
        all_nodes = self.get_all_nodes()
        new_generations = [self.active_gen_id, self.pending_gen_id]
        for node in all_nodes:
            if node.generation_id not in new_generations:
                nodes.append(node)

        nodes.sort(key=lambda n: n.generation_id)

        return nodes

    def get_all_nodes(self, generation_id=None, is_running=None):
        matching_nodes = InfrastructureNode.objects.filter(
            deployment_name=self.deployment_name,
        )
        if generation_id:
            matching_nodes = matching_nodes.filter(generation_id=generation_id)
        if is_running is not None:
            matching_nodes = matching_nodes.filter(is_running=is_running)

        configured_nodes = []
        for node in matching_nodes:
            node.set_aws_conns(self.ec2conn, self.rdsconn)
            deploy_conf = self.deployment_confs[node.aws_type].get(
                node.name, None)
            if deploy_conf is None:
                # We don't have a config for this named node
                # If it's not running though, it's probably from an old
                # deployment and we've since changed our infrastructure
                # configuration, so it's not worth worrying about
                if node.is_running:
                    logger.warning(
                        "No DEPLOYMENTS configuration exists in the <%s> "
                        "deployment for the <%s> node with the name <%s>",
                        self.deployment_name,
                        node.aws_type,
                        node.name,
                    )
                    logger.info(
                        "Available configurations: %s",
                        self.deployment_confs[node.aws_type].keys(),
                    )
            else:
                node.set_deployment_info(
                    self.deployment_confs[node.aws_type][node.name])
                configured_nodes.append(node)

        return configured_nodes

    def get_node(self, aws_type, node_name, generation_id, is_running=1):
        matching_nodes = InfrastructureNode.objects.filter(
            deployment_name=self.deployment_name,
            generation_id=generation_id,
            aws_type=aws_type,
            name=node_name,
            is_running=is_running,
        )
        if len(matching_nodes) > 1:
            raise Exception('More than one matching node')
        elif len(matching_nodes) == 1:
            node = matching_nodes[0]
            node.set_aws_conns(self.ec2conn, self.rdsconn)
            node.set_deployment_info(
                self.deployment_confs[node.aws_type][node.name])
            return node
        else:
            return None

    def set_active_node(self, aws_type, node_name, boto_object):
        if self.active_gen_id:
            gen_id = self.active_gen_id
        else:
            gen_id = self.pending_gen_id

        return self.set_node(
            aws_type,
            node_name,
            gen_id,
            boto_object,
            is_active=True)

    def set_pending_node(self, aws_type, node_name, boto_object):
        return self.set_node(
            aws_type,
            node_name,
            self.pending_gen_id,
            boto_object,
            is_active=False)

    def set_node(
        self, aws_type, node_name, generation_id, boto_object, is_active,
    ):

        aws_id = boto_object.id

        matching_nodes = InfrastructureNode.objects.filter(
            aws_type=aws_type,
            aws_id=aws_id,
            deployment_name=self.deployment_name,
        )
        if len(matching_nodes) == 1:
            node = matching_nodes[0]
        else:
            node = self.get_blank_node(aws_type)

        node.generation_id = generation_id
        node.deployment_name = self.deployment_name
        node.aws_type = aws_type
        node.aws_id = aws_id
        node.name = node_name
        node.creation_date = datetime.now()
        node.is_running = 1
        node.is_active_generation = is_active

        node.save()

    def get_new_rds_label(self, node_name, version, is_active=False):
        counter = self.pending_gen_id
        if is_active:
            counter = self.active_gen_id

        rds_label = PstatRdsId(
            'pstat' + self.deployment_name, version, counter)
        return rds_label

    def verify_running_state(self, nodes):
        for node in nodes:
            node.verify_running_state()

    def verify_active_deployment_state(self):
        """
        Ensures that all node entries match nodes. If an entry is found for an
        ``is_running`` node that isn't running, that entry is updated.

        Nodes that actually exist but aren't recorded are NOT affected.
        """
        nodes = self.get_all_active_nodes()
        self.verify_running_state(nodes)

    def verify_pending_deployment_state(self):
        nodes = self.get_all_pending_nodes()
        self.verify_running_state(nodes)

    def verify_old_deployment_state(self):
        nodes = self.get_all_old_nodes()
        self.verify_running_state(nodes)

    def verify_deployment_state(self, verify_old=True):
        """
        Ensures that all node entries match nodes. If an entry is found for an
        ``is_running`` node that isn't running, that entry is updated.

        Nodes that actually exist but aren't recorded are NOT affected.
        """
        self.verify_pending_deployment_state()
        self.verify_active_deployment_state()
        if verify_old:
            self.verify_old_deployment_state()

    def get_inoperational_active_nodes(self):
        """
        Get a list of configured nodes that aren't operational.

        If no running node exists to match a configuration, a mock node is
        returned in its place with no aws_id.
        """
        inoperational = []

        # Ensure that all roles are filled exactly once with operational nodes
        for aws_type, confs in self.deployment_confs.items():
            for node_name, node_confs in confs.items():
                node = self.get_active_node(aws_type, node_name)
                if not node:
                    mock_node = self.get_blank_node(aws_type)
                    mock_node.name = node_name
                    inoperational.append(mock_node)
                    logger.info("Missing node: %s-%s" % (aws_type, node_name))
                    continue
                if not node.is_operational:
                    inoperational.append(node)

        return inoperational

    def get_unhealthy_active_nodes(self):
        """
        Get a list of configured nodes that don't exist or aren't healthy.
        """
        nodes = self.get_all_active_nodes()

        # Check that all running nodes are healthy
        unhealthy = [
            node for node in nodes
            if node.is_running and not node.is_healthy
        ]

        # Ensure that all roles are filled exactly once with healthy nodes
        for aws_type, confs in self.deployment_confs.items():
            for node_name, node_confs in confs.items():
                node = self.get_active_node(aws_type, node_name)
                if not node:
                    mock_node = self.get_blank_node(aws_type)
                    mock_node.name = node_name
                    unhealthy.append(mock_node)
                    logger.info("Missing node: %s-%s" % (aws_type, node_name))
                    continue
                if not node.is_healthy:
                    unhealthy.append(node)
                    logger.info("Node unhealthy: %s" % node)

        return unhealthy

    def get_unhealthy_pending_nodes(self):
        """
        Get a list of configured nodes that don't exist or aren't healthy.
        """
        nodes = self.get_all_pending_nodes()

        # Check that all running nodes are healthy
        unhealthy = [
            node for node in nodes
            if node.is_running and not node.is_healthy
        ]

        # Ensure that all roles are filled exactly once with healthy nodes
        for aws_type, confs in self.deployment_confs.items():
            for node_name, node_confs in confs.items():
                node = self.get_pending_node(aws_type, node_name)
                if not node:
                    mock_node = self.get_blank_node(aws_type)
                    mock_node.name = node_name
                    unhealthy.append(mock_node)
                    logger.info("Missing node: %s-%s" % (aws_type, node_name))
                    continue
                if not node.is_healthy:
                    unhealthy.append(node)
                    logger.info("Node unhealthy: %s" % node)

        return unhealthy

    def active_is_healthy(self):
        """
        Determine if the active generation is fully healthy.
        """
        unhealthy_nodes = self.get_unhealthy_active_nodes()
        if unhealthy_nodes:
            return False

        return True

    def active_is_fully_operational(self):
        inoperational_nodes = self.get_inoperational_active_nodes()
        if inoperational_nodes:
            return False
        return True

    def pending_is_healthy(self):
        """
        Determine if the pending generation is fully healthy.
        """
        unhealthy_nodes = self.get_unhealthy_pending_nodes()
        if unhealthy_nodes:
            return False
        return True

    def repair_active_generation(
        self, force_operational=False, wait_until_operational=True,
    ):
        """
        Ensure that all healthy active-generation nodes are operational.

        ``force_operational`` If True, even non-healthy active-generation nodes
        will be made operational.
        ``wait_until_operational`` If False, doesn't wait for the nodes to
        become fully operational.

        Returns any nodes that were made operational by this action.
        """
        if self.active_is_fully_operational():
            logger.info("All active nodes are operational")
            return []

        nodes = self.get_inoperational_active_nodes()

        made_operational = []
        for node in nodes:
            if not node.aws_id:
                logger.warning(
                    "Node missing: %s- %s",
                    node.aws_type,
                    node.name,
                )
                continue
            if not node.is_operational:
                if node.is_healthy or force_operational:
                    logger.info("Making node operational: %s" % node)
                    node.make_operational(force_operational=force_operational)
                    made_operational.append(node)
                else:
                    logger.warning("Node unhealthy: %s" % node.boto_instance)
            else:
                logger.debug("Node operational: %s" % node)

        fixed_nodes = copy(made_operational)
        # Wait til of these nodes are actually operational
        if len(fixed_nodes) == 0:
            logger.info("No healthy non-operational nodes available")
            return []

        if not wait_until_operational:
            return fixed_nodes

        logger.info("Waiting until all nodes are actually operational")
        time_waited = 0
        while made_operational:
            if time_waited > MAKE_OPERATIONAL_TIMEOUT:
                raise WaitTimedOut(
                    "Timed out waiting on nodes: %s" % made_operational)
            _made_operational = made_operational[:]
            for node in _made_operational:
                if node.is_operational:
                    made_operational.remove(node)
            if made_operational:
                logger.info(
                    "%s node(s) still not operational. Waiting %ss",
                    len(made_operational),
                    WAIT_TIME,
                )
                time.sleep(WAIT_TIME)
                time_waited += WAIT_TIME

        return fixed_nodes

    def uses_rds(self):
        """
        Does this deployment uses rds. (is there an RDS node in the config)
        """
        if len(self.deployment_confs['rds'].keys()) == 0:
            return False
        return True

    def has_required_redundancy(self, node):
        """
        Determine whether the given ``node`` has the required level of
        redundancy so that it can be rendered inoperational without service
        interruption to the deployment as a whole.

        Returns True if there are redundant nodes, False otherwise.

        The logic is currently crude in that only one other node of the same
        ``aws_type`` needs to be available.
        """
        all_gen_nodes = self.get_all_nodes(node.generation_id, is_running=True)
        same_aws_nodes = [
            n
            for n in all_gen_nodes
            if n.aws_type == node.aws_type
        ]

        other_operational_nodes = []
        for other_node in same_aws_nodes:
            # Don't include the node we're checking
            if other_node.name != node.name:
                if other_node.is_operational:
                    other_operational_nodes.append(other_node)

        return bool(other_operational_nodes)

    def increment_generation(self):
        """
        Node by node, make the nodes in pending generation operational.
        """
        if not self.pending_is_healthy():
            raise Exception(
                "Pending generation must be fully healthy "
                "to increment_generation",
            )

        active_nodes = self.get_all_active_nodes()
        pending_nodes = self.get_all_pending_nodes()

        # Set is_active_generation to 0 for the active and 1 for pending
        for node in active_nodes:
            node.is_active_generation = 0
            node.save()
        for node in pending_nodes:
            node.is_active_generation = 1
            node.save()
        self._active_gen_id += 1
        self._pending_gen_id += 1

        logger.info("Generation succesfully incremented.")
        logger.info("Making nodes operational")
        self.repair_active_generation()
