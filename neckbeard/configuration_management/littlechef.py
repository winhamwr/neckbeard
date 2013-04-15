"""
Deployment provisioning (service-agnostic) for a policyst app server.
"""
import logging
import os

from fabric.api import env
from littlechef import runner as lc

from pstat.pstat_deploy import fab_out_opts
from pstat.pstat_deploy.provisioners.base import BaseProvisioner

logger = logging.getLogger('prov:littlechef')
logger.setLevel(logging.INFO)

fab_output_hides = fab_out_opts[logger.getEffectiveLevel()]
fab_quiet = fab_output_hides + ['stderr']


class LittleChefProvisioner(BaseProvisioner):
    """
    Provisioner for updating the ubuntu app server with new policystat
    application code.
    """
    def __init__(self, *args, **kwargs):
        self.kitchen_path = kwargs.pop('kitchen_path')
        self.chef_roles = kwargs.pop('chef_roles')

        super(LittleChefProvisioner, self).__init__(*args, **kwargs)

    def do_first_launch_config(self):
        lc.deploy_chef(ask="no")

    def do_update(self, first_run=False, *args, **kwargs):
        env.verbose = "true"
        self._configure_lc()
        if first_run:
            self.do_first_launch_config()

        initial_cwd = os.getcwd()
        os.chdir(self.kitchen_path)

        # Run chef-solo for all of our configured roles
        for chef_role in self.chef_roles:
            lc.role(chef_role)

        os.chdir(initial_cwd)

    def _configure_lc(self):
        lc.env.user = env.user
        lc.env.host_string = env.host_string
        lc.env.node_work_path = '/tmp/chef-solo'
