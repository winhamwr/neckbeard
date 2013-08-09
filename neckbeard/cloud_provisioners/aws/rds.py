"""
Deployment configuration for the RDS database node.
"""
import logging
import re
import time
import urllib
from collections import defaultdict
from datetime import datetime, timedelta

import dateutil.parser
from boto import rds
from boto.exception import BotoServerError
from dateutil.tz import tzlocal
from fabric.api import prompt

from neckbeard.cloud_provisioners import BaseNodeDeployment

LAUNCH_REFRESH = 15  # Seconds to wait before refreshing RDS checks

logger = logging.getLogger('aws:rds')

MAX_RESTORABLE_LAG = timedelta(minutes=15)
IP_SERVICE_URL = 'http://checkip.dyndns.com'

# TODO: Make this a hook to get your app's version
DEPLOYED_APP_VERSION = "1.0"
# TODO: Pull this from the configuration. It contains customer parameters for
# the parameter group
DB_PARAMETER_GROUPS = defaultdict(dict)


class RdsNodeDeployment(BaseNodeDeployment):
    """
    Deployment controller for an RDS database node.
    """

    def __init__(self, *args, **kwargs):
        super(RdsNodeDeployment, self).__init__(*args, **kwargs)

        self.seed_snapshot_id = None
        self.seed_master_password = None
        if self.seed_node:
            conf = self.seed_node._deployment_info['conf']
            self.seed_master_password = conf['rds_master_password']

        self._local_ip = None

    def get_ip(self):
        if self._local_ip:
            return self._local_ip

        max_retries = 10
        retries = 0
        ip = None
        while not ip:
            try:
                response = urllib.urlopen(IP_SERVICE_URL).read()
                match = re.search('\d+\.\d+\.\d+\.\d+', response)
                if match:
                    ip = match.group(0)
                else:
                    logger.error(
                        'Error getting IP from %s. Aborting' % IP_SERVICE_URL)
                    exit(1)
                logger.info("Your IP: %s", ip)
            except:
                if retries > max_retries:
                    raise
                retries += 1
                logger.warning(
                    "Error attempting to determine IP from %s",
                    IP_SERVICE_URL)
                time.sleep(5)

        self._local_ip = ip

        return self._local_ip

    def verify_seed_data(self, node, retries_remaining=3):
        """
        Ensure that the seed data you received is correct.
        """
        pass

    def get_seed_data(self):
        """
        Ensure that the seed node has a recent latest restorable time,
        otherwise allow the user to create a snapshot to restore from.
        """
        if self.seed_node and self.seed_verification:
            # TODO: Hook to do maintenance announcements, etc
            self._create_snapshot()
            return

        if self.seed_node:
            restoration_lag = self._get_restorable_lag()
            if restoration_lag > MAX_RESTORABLE_LAG:
                logger.critical("DB restoration lag: %s", restoration_lag)
                logger.critical("DB restoration lag too high.")
            else:
                return

        opts = ['F', 'S', 'E']
        action = None
        while action not in opts:
            action = prompt(
                "Create (S)napshot, use (E)xisting snapshot or (F)ail?")

        if action == 'S':
            self._create_snapshot()
        elif action == 'E':
            self.seed_snapshot_id = prompt("Enter snapshot id:")
        else:
            logger.critical("FAIL. DB restoration lag too high")
            exit(1)

    def _create_snapshot(self):
        instance = self.seed_node.boto_instance
        now = datetime.now()
        nowstr = now.strftime('%Y%m%d-%H%M%S')
        label = '%s-%sseed%s' % (
            self.deployment.deployment_name,
            self.node_name,
            nowstr,
        )
        restoration_snapshot = instance.snapshot(label)
        self.seed_snapshot_id = restoration_snapshot.id

    def _get_restorable_lag(self):
        """
        Get a timedelta representing the lag between now and the latest
        restorable time from the seed node.
        """
        seed_instance = self.seed_node.boto_instance
        latest_restorable_time = seed_instance.latest_restorable_time
        # Parse the time from the ISO 8601 string
        latest_restorable_time = dateutil.parser.parse(latest_restorable_time)

        restoration_lag = datetime.now(
            tzlocal()
        ) - latest_restorable_time

        return restoration_lag

    def create_new_node(self):
        """
        Launches and configures a new rds instance.
        """
        # Start up and connect to the Amazon RDS instance
        rds_label = str(self.deployment.get_new_rds_label(
            self.node_name, DEPLOYED_APP_VERSION))

        rds_instance = self.launch(rds_label)

        if self.is_active:
            self.deployment.set_active_node(
                'rds', self.node_name, rds_instance)
        else:
            self.deployment.set_pending_node(
                'rds', self.node_name, rds_instance)

        # Wait for node registration to complete
        time.sleep(2)

        # Doing this at the end to give the node-setting time to propogate
        return self.get_node()

    def launch(self, rds_label):
        """
        Launches an RDS instance with the given ``rds_label``. Takes in to
        account the seed node settings to start the database with the
        appropriate data.

        Returns the launched boto rds instance.
        """
        conf = self.deployment.deployment_confs['rds'][self.node_name]['conf']

        rds_label = str(rds_label)

        if self.seed_snapshot_id:
            logger.info(
                "Creating RDS instance: %s from snapshot: %s",
                rds_label,
                self.seed_snapshot_id,
            )

            # Wait for the snapshot to complete
            snapshot = self.deployment.rdsconn.get_all_dbsnapshots(
                snapshot_id=self.seed_snapshot_id)[0]
            while snapshot.status != 'available':
                logger.info(
                    "RDS Snapshot pending. Waiting %ss",
                    LAUNCH_REFRESH)
                time.sleep(LAUNCH_REFRESH)
                snapshot = self.deployment.rdsconn.get_all_dbsnapshots(
                    snapshot_id=self.seed_snapshot_id)[0]

            rdsconn = self.deployment.rdsconn
            db_instance = rdsconn.restore_dbinstance_from_dbsnapshot(
                identifier=snapshot.id,
                instance_id=rds_label,
                instance_class=conf['rds_instance_class'],
                availability_zone=conf['rds_availability_zone'])
        else:
            if self.seed_node:
                seed_instance = self.seed_node.boto_instance
                logger.info(
                    "Creating RDS instance: %s using PiT restore from: %s",
                    rds_label,
                    seed_instance.id)

                # Create using rdsconn.restore_db_instance_from_dbsnapshot
                rdsconn = self.deployment.rdsconn
                db_instance = rdsconn.restore_dbinstance_from_point_in_time(
                    source_instance_id=seed_instance.id,
                    target_instance_id=rds_label,
                    use_latest=True,
                    dbinstance_class=conf['rds_instance_class'],
                    availability_zone=conf['rds_availability_zone'],
                )

            else:
                # Creating a new, blank, DB
                logger.info("Creating new blank RDS instance: %s" % rds_label)
                db_instance = self.deployment.rdsconn.create_dbinstance(
                    id=rds_label,
                    allocated_storage=conf['rds_allocated_storage'],
                    instance_class=conf['rds_instance_class'],
                    master_username=conf['rds_master_username'],
                    master_password=conf['rds_master_password'],
                    security_groups=conf['rds_security_groups'],
                    availability_zone=conf['rds_availability_zone'],
                    preferred_maintenance_window=conf['rds_preferred_maintenance_window'],  # NOQA
                    backup_retention_period=conf['rds_backup_retention_period'],  # NOQA
                    preferred_backup_window=conf['rds_preferred_backup_window'],  # NOQA
                    multi_az=conf['rds_multi_az'])

        # Wait for the RDS instance request to actually appear
        return db_instance

    def _modify_db_config(self, node, conf, apply_immediately=False):
        """
        Modify the db parameters based on ``conf``.

        Returns ``True`` if a database restart was required.
        """
        node.refresh_boto_instance()

        logger.info("Modifying RDS DB parameters")
        # Need to modify the db to make sure all of the properties are set
        self.deployment.rdsconn.modify_dbinstance(
            id=node.boto_instance.id,
            allocated_storage=conf['rds_allocated_storage'],
            instance_class=conf['rds_instance_class'],
            master_password=conf['rds_master_password'],
            security_groups=conf['rds_security_groups'],
            preferred_maintenance_window=conf['rds_preferred_maintenance_window'],  # NOQA
            backup_retention_period=conf['rds_backup_retention_period'],
            preferred_backup_window=conf['rds_preferred_backup_window'],
            param_group=conf['rds_parameter_group'],
            multi_az=conf['rds_multi_az'],
            apply_immediately=apply_immediately)

        # Small sleep so that our changes have time to register
        time.sleep(3)
        # Wait for db modifications to complete
        self.wait_until_created(node)

        node.refresh_boto_instance()
        if node.boto_instance.pending_modified_values \
           and node.boto_instance.status != 'modifying':
            # Some modifications are still pending, do a hard restart since
            # that's required for MultiAZ
            logger.info(
                "DB has pending modified values and state of %s, a restart "
                "might be required",
                node.boto_instance.status)
            if self.is_active:
                # Don't allow restarting active nodes
                logger.warning("---")
                logger.warning(
                    "The DB node is live, and a DB restart might be required. "
                    "Please manually verify the database parameters"
                )
                logger.warning("---")
                return False

            node.boto_instance.reboot()
            return True

        return False

    def deploy(self, node, first_run=False):
        self.wait_until_created(node)
        conf = self.deployment.deployment_confs['rds'][self.node_name]['conf']

        # First need to make sure the parameter group is configured properly
        self.configure_parameter_group(
            conf['rds_parameter_group'],
            DB_PARAMETER_GROUPS[conf['rds_parameter_group']])
        self.wait_until_created(node)

        if first_run or self._parameters_differ(node, conf):
            # Only need to modify the instance on the first run
            required_restart = self._modify_db_config(
                node, conf, apply_immediately=first_run)

            if required_restart:
                # Small sleep so that our changes have time to register
                time.sleep(3)
                # Wait for db modifications to complete
                self.wait_until_created(node)

    def _parameters_differ(self, node, conf):
        """
        Determine whether the current database configuration differs from the
        configuration defined in the ``conf`` dictionary.
        """
        node.refresh_boto_instance()

        checked_params = [
            'rds_allocated_storage',
            'rds_instance_class',
            'rds_preferred_maintenance_window',
            'rds_backup_retention_period',
            'rds_preferred_backup_window',
            'rds_multi_az',
        ]

        groups_changed = False
        current_security_group = node.boto_instance.security_group.name
        if current_security_group not in conf['rds_security_groups']:
            logger.info(
                "param %s defined: %s actual: %s",
                'rds_security_groups',
                conf['rds_security_groups'],
                getattr(node.boto_instance, 'security_group').name)
            groups_changed = True
        current_parameter_group = node.boto_instance.parameter_group.name
        if current_parameter_group != conf['rds_parameter_group']:
            logger.info(
                "param %s defined: %s actual: %s",
                'rds_parameter_group',
                conf['rds_parameter_group'],
                getattr(node.boto_instance, 'parameter_group'))
            groups_changed = True

        diff_params = []
        for checked_param in checked_params:
            rds_param = checked_param.replace('rds_', '')
            defined_val = str(
                conf[checked_param]
            ).lower().strip()
            actual_val = str(
                getattr(node.boto_instance, rds_param)
            ).lower().strip()
            if defined_val != actual_val:
                diff_params.append(checked_param)

        if diff_params or groups_changed:
            for diff_param in diff_params:
                rds_param = diff_param.replace('rds_', '')
                defined_val = str(conf[diff_param]).lower().strip()
                actual_val = str(
                    getattr(node.boto_instance, rds_param)
                ).lower().strip()
                logger.info(
                    "param %s defined: %s actual: %s",
                    diff_param,
                    defined_val,
                    actual_val)

            return True

        logger.info("DB Parameters Already Synced")
        return False

    def wait_until_created(self, node):
        start_time = time.time()
        waited = False
        while not self.creation_complete(node):
            waited = True
            logger.info(
                "RDS DB still pending. Status: %s",
                node.boto_instance.status,
            )
            time.sleep(LAUNCH_REFRESH)
        if waited:
            logger.info("Waited %.1fs for DB", time.time() - start_time)

    def creation_complete(self, node):
        node.refresh_boto_instance()
        return node.boto_instance.status == 'available'

    def _get_all_db_parameters(self, group_name):
        """
        Create the named parameter group (if needed)
        and return a list of all the db parameters, accounting for request
        pagination.
        """
        rdsconn = self.deployment.rdsconn
        all_parameters = []
        try:
            all_parameters = rdsconn.get_all_dbparameters(
                groupname=group_name,
                max_records=100,
            )
        except BotoServerError:
            logger.info(
                "RDS Parameter Group %s doesn't exist. Creating it.",
                group_name,
            )
            # TODO: Detect the message `Invalid parameter group name:` Message
            # to ensure that this isn't some other kind of error
            rdsconn.create_parameter_group(name=group_name)
            all_parameters = rdsconn.get_all_dbparameters(
                groupname=group_name,
                max_records=100,
            )

        def _get_pagination_marker(parameter_group):
            # Determine if we got paginated results
            pagination_marker = None
            if hasattr(parameter_group, 'Marker'):
                pagination_marker = parameter_group.Marker

            return pagination_marker

        pagination_marker = _get_pagination_marker(all_parameters)

        while pagination_marker:
            additional_parameters = rdsconn.get_all_dbparameters(
                groupname=group_name,
                max_records=100,
                marker=pagination_marker,
            )
            all_parameters.update(additional_parameters)

            pagination_marker = _get_pagination_marker(additional_parameters)

        return all_parameters

    def _validate_desired_parameter_group_configuration(
        self,
        group_name,
        confs,
    ):
        """
        Ensure that we're using proper types for our desired parameters.
        """
        valid_types = rds.parametergroup.Parameter.ValidTypes
        for name, desired_value in confs.items():
            is_valid = False
            for type_method in valid_types.values():
                if isinstance(desired_value, type_method):
                    is_valid = True
                    break
            if not is_valid:
                logger.critical(
                    "Desired DB Parameter config error for group: %s",
                    group_name,
                )
                logger.critical(
                    "Desired value of '%s' for '%s' is an invalid type",
                )
                valid_type_names = ', '.join(valid_types.keys())
                logger.critical("Should be one of: %s", valid_type_names)
                exit(1)

    def configure_parameter_group(self, group_name, confs):
        """
        Configure the RDS parameter group given by ``group_name`` with a
        dict of ``confs`` with key => values for the parameters to modify.
        """
        self._validate_desired_parameter_group_configuration(
            group_name=group_name,
            confs=confs,
        )
        current_parameters = self._get_all_db_parameters(group_name)

        parameters_to_modify = []
        for parameter_name, desired_value in confs.items():
            try:
                current_parameter = current_parameters[parameter_name]
            except KeyError:
                logger.warning(
                    "RDS Parameter '%s' does not currently exist",
                    parameter_name,
                )
                current_parameter = rds.parametergroup.Parameter(
                    group=current_parameters,
                    name=parameter_name,
                )
                # Set the expected data type for validation
                # The default is string
                if isinstance(desired_value, int):
                    current_parameter.type = 'integer'
                elif isinstance(desired_value, bool):
                    current_parameter.type = 'boolean'
                elif isinstance(desired_value, str):
                    current_parameter.type = 'string'

            if current_parameter.type == str:
                # Work-around for a boto 1.9 Parameter.type initialization bug
                # Remove this when we drop support for boto 1.9
                current_parameter.type = 'string'
            if current_parameter.value != desired_value:
                logger.info(
                    "RDS Parameter Group %s requires change for %s",
                    group_name,
                    parameter_name,
                )
                logger.info("Current value: %s", current_parameter.value)
                logger.info("Desired value: %s", desired_value)
                current_parameter.value = desired_value
                current_parameter.apply_method = 'immediate'
                parameters_to_modify.append(current_parameter)

        if parameters_to_modify:
            logger.info("Modifying RDS Parameter Group: %s", group_name)
            self.deployment.rdsconn.modify_parameter_group(
                name=group_name,
                parameters=parameters_to_modify,
            )
