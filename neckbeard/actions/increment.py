import logging

from fabric.api import env, task, require

from neckbeard.actions.contrib_hooks import (
    notifies_hipchat,
    _take_temporary_pagerduty,
)
from neckbeard.environment_manager import Deployment

INCREMENT_START_MSG = (
    '%(deployer)s <strong>Incrementing</strong> '
    '<em>%(deployment_name)s</em>'
)
INCREMENT_END_MSG = (
    '%(deployer)s <strong>Incremented</strong> '
    '<em>%(deployment_name)s</em>'
    "<br />Took: <strong>%(duration)s</strong>s"
)

logger = logging.getLogger('actions.override')


@task
@notifies_hipchat(start_msg=INCREMENT_START_MSG, end_msg=INCREMENT_END_MSG)
def increment():
    """
    Move the fully-healthy pending generation to the ACTIVE state.
    """
    require('_deployment_name')
    require('_deployment_confs')

    deployment = Deployment(
        env._deployment_name,
        env._deployment_confs['ec2'],
        env._deployment_confs['rds'],
        env._deployment_confs['elb'],
    )
    deployment.verify_deployment_state()

    try:
        deployment.increment_generation()
    except:
        logger.critical("Error incrementing generation")
        raise

    pagerduty_conf = env._deployment_confs['conf'].get('pagerduty', {})
    if pagerduty_conf.get('temporarily_become_oncall', False):
        _take_temporary_pagerduty(
            duration=pagerduty_conf.get('temporary_oncall_duration'),
            api_key=pagerduty_conf.get('api_key'),
            user_id=pagerduty_conf.get('user_id'),
            project_subdomain=pagerduty_conf.get('project_subdomain'),
            schedule_key=pagerduty_conf.get('schedule_key'),
        )

    logger.warning("Previously-active generation still exists in the "
                   "loadbalancer. Use `terminate` to remove it")
