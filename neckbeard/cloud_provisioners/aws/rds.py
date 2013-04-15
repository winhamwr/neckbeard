"""
Deployment configuration for the RDS database node.
"""
from datetime import datetime, timedelta
import logging
import time
import urllib
import re
from multiprocessing import Process

import dateutil.parser
from dateutil.tz import tzlocal
from django.core.management import setup_environ
from fabric.api import prompt

from boto import rds
from boto.exception import BotoServerError

from pstat.pstat_deploy.deployers.base import BaseNodeDeployment
from pstat.pstat_deploy.targets import VERSION as PSTAT_VERSION
from pstat.pstat_deploy.targets import DB_PARAMETER_GROUPS

LAUNCH_REFRESH = 15  # Seconds to wait before refreshing RDS checks

logger = logging.getLogger('deploy:rds')
logger.setLevel(logging.INFO)

MAX_RESTORABLE_LAG = timedelta(minutes=15)
IP_SERVICE_URL = 'http://checkip.dyndns.com'


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

    def make_maintenance_announcement(self, retries_remaining=3):
        """
        Connect to the database and make a maintenance announcement so that we
        can check that the announcement carries through.
        """
        seed_instance = self.seed_node.boto_instance
        # First need to authorize this ip to connect to the DB
        security_group = seed_instance.security_group
        ip = self.get_ip()
        cidr = "%s/32" % ip
        try:
            security_group.authorize(cidr_ip=cidr)
        except BotoServerError:
            # Authorization might already exist
            pass

        # Using multiprocess to avoid Django database-switching madness
        import pstat.settings as settings
        process_kwargs = {
            'settings': settings,
            'seed_instance': seed_instance,
            'seed_master_password': self.seed_master_password,
        }
        make_announcement_p = Process(
            target=make_announcement, kwargs=process_kwargs)
        make_announcement_p.start()
        make_announcement_p.join()

        if make_announcement_p.exitcode != 0:
            if retries_remaining > 0:
                logger.warning("Error setting announcement")
                logger.warning("%s retries remaining", retries_remaining)
                return self.make_maintenance_announcement(
                    retries_remaining=retries_remaining - 1)
            else:
                logger.critical("Error setting announcement")
                logger.critical("All retries exhausted. Failing.")
                exit(1)

        # Now remove the authorization for this ip
        security_group.revoke(cidr_ip=cidr)

    def verify_seed_data(self, node, retries_remaining=3):
        """
        Ensure that the maintenance announcement exists and remove it.
        """
        rds_instance = node.boto_instance
        conf = self.deployment.deployment_confs['rds'][self.node_name]['conf']

        # First need to authorize this ip to connect to the DB
        security_group = rds_instance.security_group
        ip = self.get_ip()
        cidr = "%s/32" % ip
        try:
            security_group.authorize(cidr_ip=cidr)
        except BotoServerError:
            # Authorization might already exist
            logger.warning("BotoServerError attempting to authorize IP")

        # Using multiprocess to avoid Django database-switching madness
        import pstat.settings as settings
        process_kwargs = {
            'settings': settings,
            'rds_instance': rds_instance,
            'master_password': conf['rds_master_password'],
        }
        verify_announcement_p = Process(
            target=verify_announcement, kwargs=process_kwargs)
        verify_announcement_p.start()
        verify_announcement_p.join()

        if verify_announcement_p.exitcode != 0:
            if retries_remaining > 0:
                logger.warning("Error verifying announcement")
                logger.warning("%s retries remaining", retries_remaining)
                return self.verify_seed_data(
                    node, retries_remaining=retries_remaining - 1)
            else:
                logger.critical("Error verifying announcement")
                logger.critical("All retries exhausted. Failing.")
                exit(1)

        # Now remove the authorization for this ip
        try:
            security_group.revoke(cidr_ip=cidr)
        except BotoServerError:
            # If this goes quickly, authorization might be in the authoring
            # state
            pass

    def get_seed_data(self):
        """
        Ensure that the seed node has a recent latest restorable time,
        otherwise allow the user to create a snapshot to restore from.
        """
        if self.seed_node and self.seed_verification:
            self.make_maintenance_announcement()
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
        label = '%s-%sseed%s' % \
              (self.deployment.deployment_name, self.node_name, nowstr)
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

        restoration_lag = datetime.now(tzlocal()) \
                        - latest_restorable_time

        return restoration_lag

    def create_new_node(self):
        """
        Launches and configures a new rds instance.
        """
        # Start up and connect to the Amazon RDS instance
        rds_label = str(self.deployment.get_new_rds_label(
            self.node_name, PSTAT_VERSION))

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
                "Creating RDS instance: %s from snapshot: %s" % \
                (rds_label, self.seed_snapshot_id))

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
                db_instance = self.deployment.rdsconn\
                            .restore_dbinstance_from_point_in_time(
                    source_instance_id=seed_instance.id,
                    target_instance_id=rds_label,
                    use_latest=True,
                    dbinstance_class=conf['rds_instance_class'],
                    availability_zone=conf['rds_availability_zone'])

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
            defined_val = str(conf[checked_param]).lower().strip()
            actual_val = str(getattr(node.boto_instance, rds_param))\
                       .lower().strip()
            if defined_val != actual_val:
                diff_params.append(checked_param)

        if diff_params or groups_changed:
            for diff_param in diff_params:
                rds_param = diff_param.replace('rds_', '')
                defined_val = str(conf[diff_param]).lower().strip()
                actual_val = str(getattr(node.boto_instance, rds_param))\
                           .lower().strip()
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

    def configure_parameter_group(self, group_name, confs):
        """
        Configure the RDS paramater group given by ``group_name`` with a
        dict of ``confs`` with key => values for the paramters to modify.
        """
        pg = rds.parametergroup.ParameterGroup(self.deployment.rdsconn)
        pg.name = group_name

        for name, value in confs.items():
            param = rds.parametergroup.Parameter(pg, name)
            param._value = value
            param.apply_type = 'immediate'
            param.apply(immediate=True)


def make_announcement(settings, seed_instance, seed_master_password):
    # Connect to the database and add the announcement
    settings.DATABASES['default']['ENGINE'] = 'django.db.backends.mysql'
    host, port = seed_instance.endpoint
    settings.DATABASES['default']['HOST'] = host
    settings.DATABASES['default']['PORT'] = port
    settings.DATABASES['default']['USER'] = seed_instance.master_username
    settings.DATABASES['default']['PASSWORD'] = seed_master_password
    settings.DATABASES['default']['NAME'] = 'policystat'
    setup_environ(settings)

    # pylint: disable=W0404
    from announcements.models import Announcement
    from django.contrib.auth.models import User
    # pylint: enable=W0404
    if Announcement.objects.count() == 0:
        admin = User.objects.filter(is_superuser=True).order_by('pk')[0]
        Announcement.objects.create(
            title="Maintenance In Progress",
            content=(
                "Policy approvals, comments, edits and other changes will "
                "NOT persist until maintenance is complete"
            ),
            creator=admin,
            site_wide=True)

    count = Announcement.objects.all().count()
    if count != 1:
        exit(1)
    exit(0)


def verify_announcement(settings, rds_instance, master_password):
    # Connect to the database and add the announcement
    settings.DATABASES['default']['ENGINE'] = 'django.db.backends.mysql'
    host, port = rds_instance.endpoint
    settings.DATABASES['default']['HOST'] = host
    settings.DATABASES['default']['PORT'] = port
    settings.DATABASES['default']['USER'] = rds_instance.master_username
    settings.DATABASES['default']['PASSWORD'] = master_password
    settings.DATABASES['default']['NAME'] = 'policystat'
    setup_environ(settings)

    # Keeping the import inside this function because it's meant for
    # multiprocessing
    # pylint: disable=W0404
    from announcements.models import Announcement
    from MySQLdb import OperationalError
    from django.db import connection
    # pylint: enable=W0404
    try:
        if Announcement.objects.count() == 0:
            logger.critical("No Announcements in new DB")
            exit(1)
    except OperationalError, e:
        logger.warning(
            "Error connecting to the MySql database to verify the "
            "announcement. Waiting 30 seconds and retrying")
        logger.warning("Error Was: %s", e)
        # Reset the database connection
        connection.connection.close()
        connection.connection = None
        time.sleep(30)
        if Announcement.objects.count() == 0:
            logger.critical("No Announcements in new DB")
            exit(1)
    Announcement.objects.all().delete()

    exit(0)
