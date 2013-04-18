import logging
import time

from boto.exception import BotoServerError
from multiprocessing import Process

from django.core.management import setup_environ

logger = logging.getLogger('aws:contrib')


def make_django_maintenance_announcement(rds_provisioner, retries_remaining=3):
    """
    Connect to the database and make a maintenance announcement so that we
    can check that the announcement carries through.
    """
    seed_instance = rds_provisioner.seed_node.boto_instance
    # First need to authorize this ip to connect to the DB
    security_group = seed_instance.security_group
    ip = rds_provisioner.get_ip()
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
        'seed_master_password': rds_provisioner.seed_master_password,
    }
    make_announcement_p = Process(
        target=_make_django_maintenance_announcement,
        kwargs=process_kwargs,
    )
    make_announcement_p.start()
    make_announcement_p.join()

    if make_announcement_p.exitcode != 0:
        if retries_remaining > 0:
            logger.warning("Error setting announcement")
            logger.warning("%s retries remaining", retries_remaining)
            return rds_provisioner.make_maintenance_announcement(
                retries_remaining=retries_remaining - 1)
        else:
            logger.critical("Error setting announcement")
            logger.critical("All retries exhausted. Failing.")
            exit(1)

    # Now remove the authorization for this ip
    security_group.revoke(cidr_ip=cidr)


def _make_django_maintenance_announcement(
    settings, seed_instance, seed_master_password,
):
    """
    Post-fork call to connect to the database and set an announcement.
    """
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


def verify_django_maintenance_announcement(
    rds_deployer, node, retries_remaining=3,
):
    """
    Ensure that the maintenance announcement exists and remove it.
    """
    rds_instance = node.boto_instance
    conf = rds_deployer.deployment.deployment_confs[
        'rds'
    ][rds_deployer.node_name]['conf']

    # First need to authorize this ip to connect to the DB
    security_group = rds_instance.security_group
    ip = rds_deployer.get_ip()
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
        target=_verify_django_maintenance_announcement,
        kwargs=process_kwargs,
    )
    verify_announcement_p.start()
    verify_announcement_p.join()

    if verify_announcement_p.exitcode != 0:
        if retries_remaining > 0:
            logger.warning("Error verifying announcement")
            logger.warning("%s retries remaining", retries_remaining)
            return rds_deployer.verify_seed_data(
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


def _verify_django_maintenance_announcement(
    settings, rds_instance, master_password,
):
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
