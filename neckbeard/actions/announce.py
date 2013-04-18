import logging

from fabric.api import task, require

from neckbeard.actions.contrib_hooks import (
    _get_git_repo,
    _announce_deployment,
)

logger = logging.getLogger('actions.announce')


@task
def announce():
    require('_deployment_name')
    require('_deployment_confs')
    require('_active_gen')

    # Make sure we're in the git repo
    _get_git_repo()

    _announce_deployment()
