"""
Provisioning for a dynamic PolicyStat server with no persistance that just runs
Celery and Nginx/uwsgi.
"""
import logging

from pstat.pstat_deploy import fab_out_opts, fab_quiet_opts
from pstat.pstat_deploy.provisioners.pstat.app import (
    AppServerProvisioner,
)

logger = logging.getLogger('prov:pstat:dyno')

fab_output_hides = fab_out_opts[logger.getEffectiveLevel()]
fab_quiet = fab_quiet_opts[logger.getEffectiveLevel()]


class DynoServerProvisioner(AppServerProvisioner):
    """
    Configurations for dynamic, stateless app server.

    We differentiate between this and a normal app server by no-opping out the
    things we shouldn't configure and doing uninstallation on first run for the
    packages we don't need.
    """
    # Packages this server doesn't need
    vestigial_packages = [
        'openswan',
        'redis-server',
        'memcached',
        'sphinxsearch',
    ]

    def _configure_sphinx(self):
        pass

    def _build_search_index(self):
        return False

    def _configure_calabar(self):
        pass

    def _configure_ipsec(self):
        pass

    def _configure_pstat_cron_jobs(self):
        pass

    def _configure_email_sending(self):
        pass

    def _ensure_sphinx_running(self):
        pass

    def _configure_sphinx_cron(self):
        pass
