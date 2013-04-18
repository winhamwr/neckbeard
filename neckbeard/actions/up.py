import copy
import logging
import time
from collections import namedtuple
from datetime import datetime

from decorator import contextmanager
from fabric.api import env, task, require, prompt

from neckbeard.actions.contrib_hooks import (
    notifies_hipchat,
    _get_git_repo,
    _is_unchanged_from_head,
    _is_tagged_version,
    _push_tags,
    _take_temporary_pagerduty,
    DT_NOTIFY,
    _send_deployment_done_desktop_notification,
    _announce_deployment,
)
from neckbeard.actions.utils import (
    logs_duration,
    prompt_on_exception,
)
from neckbeard.environment_manager import Deployment
from neckbeard.cloud_provisioners.aws import (
    Ec2NodeDeployment,
    RdsNodeDeployment,
)

UP_START_MSG = (
    '%(deployer)s <strong>Deploying</strong> '
    '<em>%(deployment_name)s</em> %(generation)s '
    'From: <strong>%(git_branch)s</strong>'
)
UP_END_MSG = (
    '%(deployer)s <strong>Deployed</strong> '
    '<em>%(deployment_name)s</em> %(generation)s '
    "<br />Took: <strong>%(duration)s</strong>s"
)

logger = logging.getLogger('actions.view')
time_logger = logging.getLogger('timer')

timer = {}


@task
@notifies_hipchat(start_msg=UP_START_MSG, end_msg=UP_END_MSG)
@logs_duration(timer, output_result=True)
def up(force='n'):
    """
    Make sure that the instances for the specified generation are running and
    have current code. Will update code and deploy new EC2 and RDS instances as
    needed.
    """
    require('_deployment_name')
    require('_deployment_confs')
    require('_active_gen')

    with logs_duration(timer, timer_name='validation'):
        repo = _get_git_repo()

        # Force submodules to be updated
        with prompt_on_exception("Git submodule update failed"):
            repo.submodule_update(init=True, recursive=True)

        # Optionally require that we deploy from a tagged commit.
        git_conf = env._deployment_confs['conf'].get('git', {})
        if git_conf.get('require_tag', False):
            logger.info("Enforcing git tag requirement")
            if not _is_unchanged_from_head(repo):
                logger.critical(
                    "Refusing to deploy, uncommitted changes exist.")
                exit(1)
            if not _is_tagged_version(repo):
                logger.critical("Refusing to deploy from an untagged commit.")
                exit(1)
            _push_tags(repo)

        force = force == 'y'
        if env._active_gen:
            # Always force the active generation in operation if possible
            force = True

    logger.info("Gathering deployment state")
    with logs_duration(timer, timer_name='gather deployment state'):
        deployment = Deployment(
            env._deployment_name,
            env._deployment_confs['ec2'],
            env._deployment_confs['rds'],
            env._deployment_confs['elb'],
        )
        deployment.verify_deployment_state()

        # All rds and ec2 nodes, rds nodes first
        dep_confs = []
        dep_confs.append(('rds', sorted(env._deployment_confs['rds'].items())))
        dep_confs.append(('ec2', sorted(env._deployment_confs['ec2'].items())))

        node_deploys = []
        NodeDeploy = namedtuple(
            'NodeDeploy',
            ['aws_type', 'node_name', 'deployment', 'seed_node_name',
             'seed_deployment', 'verify_seed_data', 'provisioner_conf',
             'force'])

        pagerduty_conf = env._deployment_confs['conf'].get('pagerduty', {})
        if pagerduty_conf.get('temporarily_become_oncall', False):
            logger.info("Taking Pagerduty, temporarily")
            _take_temporary_pagerduty(
                duration=pagerduty_conf.get('temporary_oncall_duration'),
                api_key=pagerduty_conf.get('api_key'),
                user_id=pagerduty_conf.get('user_id'),
                project_subdomain=pagerduty_conf.get('project_subdomain'),
                schedule_key=pagerduty_conf.get('schedule_key'),
            )

    # Gather all of the configurations for each node, including their
    # seed deployment information
    logger.info("Gathering node configuration and status")
    with logs_duration(timer, timer_name='gather node status'):
        for aws_type, node_confs in dep_confs:
            for node_name, conf in node_confs:
                # Get the seed deployment new instances will be copied from
                seed_deployment = None
                seed_node_name = None
                if 'seed_node' in conf:
                    seed_dep_name = conf['seed_node']['deployment']
                    seed_node_name = conf['seed_node']['node']
                    verify_seed_data = conf['seed_node'].get('verify', False)

                    seed_deployment = Deployment(
                        seed_dep_name,
                        env.DEPLOYMENTS[seed_dep_name]['ec2'],
                        env.DEPLOYMENTS[seed_dep_name]['rds'],
                        env.DEPLOYMENTS[seed_dep_name]['elb'],
                    )
                    # up never deals with old nodes, so just verify pending and
                    # active to save HTTP round trips
                    seed_deployment.verify_deployment_state(verify_old=False)
                else:
                    logger.info("No seed node configured")
                    seed_node_name = None
                    seed_deployment = None
                    verify_seed_data = False
                provisioner_conf = conf['provisioning']

                node_deploy = NodeDeploy(
                    aws_type=aws_type,
                    node_name=node_name,
                    deployment=deployment,
                    seed_node_name=seed_node_name,
                    seed_deployment=seed_deployment,
                    verify_seed_data=verify_seed_data,
                    provisioner_conf=provisioner_conf,
                    force=force)
                node_deploys.append(node_deploy)

    ec2_deployers = []
    rds_deployers = []
    # Build all of the deployment objects
    logger.info("Building Node deployers")
    with logs_duration(timer, timer_name='build deployers'):
        for nd in node_deploys:
            if nd.aws_type == 'ec2':
                conf_dict = env._deployment_confs['ec2'][nd.node_name]
                node_conf = conf_dict.get('conf', {})
                conf_key = conf_dict['conf_key']
                env_confs = copy.copy(env.INSTANCES[conf_key])

                deployer = Ec2NodeDeployment(
                    nd.deployment,
                    nd.seed_deployment,
                    env._active_gen,
                    nd.aws_type,
                    nd.node_name,
                    nd.seed_node_name,
                    seed_verification=nd.verify_seed_data,
                    provisioner_conf=nd.provisioner_conf,
                    conf=node_conf,
                )
                ec2_deployers.append((env_confs, deployer))

            elif nd.aws_type == 'rds':
                conf_dict = env._deployment_confs['rds'][nd.node_name]
                node_conf = conf_dict.get('conf', {})
                deployer = RdsNodeDeployment(
                    nd.deployment,
                    nd.seed_deployment,
                    env._active_gen,
                    nd.aws_type,
                    nd.node_name,
                    nd.seed_node_name,
                    seed_verification=nd.verify_seed_data,
                    provisioner_conf=nd.provisioner_conf,
                    conf=node_conf,
                )
                rds_deployers.append(deployer)

    # Provision the RDS nodes
    with logs_duration(timer, timer_name='initial provision'):
        logger.info("Provisioning RDS nodes")
        for deployer in rds_deployers:
            if deployer.seed_verification and deployer.get_node() is None:
                _prompt_for_seed_verification(deployer)

            deployer.ensure_node_created()

        # Provision the EC2 nodes
        logger.info("Provisioning EC2 nodes")
        for env_confs, deployer in ec2_deployers:
            # Prepare the environment for deployment
            for key, value in env_confs.items():
                setattr(env, key, value)

            if deployer.seed_verification and deployer.get_node() is None:
                _prompt_for_seed_verification(deployer)

            deployer.ensure_node_created()

    # Configure the RDS nodes
    logger.info("Configuring RDS nodes")
    with logs_duration(timer, timer_name='deploy rds'):
        for deployer in rds_deployers:
            deployer.run()

    logger.info("Determining EC2 node deploy priority")
    ec2_deployers = _order_ec2_deployers_by_priority(ec2_deployers)

    # Configure the EC2 nodes
    logger.info("Deploying to EC2 nodes")
    for env_confs, deployer in ec2_deployers:
        timer_name = '%s deploy' % deployer.node_name
        with logs_duration(timer, timer_name='full %s' % timer_name):
            node = deployer.get_node()

            # Prepare the environment for deployment
            for key, value in env_confs.items():
                setattr(env, key, value)

            with seamless_modification(
                node,
                deployer.deployment,
                force_seamless=env._active_gen,
                force_operational=force,
            ):

                pre_deploy_time = datetime.now()
                with logs_duration(
                    timer,
                    timer_name=timer_name,
                    output_result=True,
                ):
                    deployer.run()
            if DT_NOTIFY:
                _send_deployment_done_desktop_notification(
                    pre_deploy_time, deployer)

    _announce_deployment()

    time_logger.info("Timing Breakdown:")
    sorted_timers = sorted(
        timer.items(),
        key=lambda x: x[1],
        reverse=True,
    )
    for timer_name, duration in sorted_timers:
        time_logger.info("%02ds- %s", duration, timer_name)


def _order_ec2_deployers_by_priority(ec2_deployers):
    """
    Re-order the deployer objects so that we deploy in the optimal node order.

    Uses the following order:
     1. Inoperative, unhealthy nodes
     2. Inoperative, healthy nodes
     3. Operational, unhealthy nodes
     4. Operational, healthy nodes
    """
    io_unhealthy = []
    io_healthy = []
    o_unhealthy = []
    o_healthy = []

    for ec2_deployer in ec2_deployers:
        env_confs, deployer = ec2_deployer
        node = deployer.get_node()
        if node.is_operational:
            if node.is_healthy:
                o_healthy.append(ec2_deployer)
            else:
                o_unhealthy.append(ec2_deployer)
        else:
            if node.is_healthy:
                io_healthy.append(ec2_deployer)
            else:
                io_unhealthy.append(ec2_deployer)

    return io_healthy + io_unhealthy + o_unhealthy + o_healthy


@contextmanager
def seamless_modification(
        node, deployment, force_seamless=True, force_operational=False):
    """
    Rotates the ``node`` in the ``deployment`` in and out of operation if
    possible to avoid service interruption. If ``force_seamless`` is True
    (default) then the user will be prompted if it's not possible to rotate in
    and out seamlessly because the required redundancy isn't met.

    Understands that only active, operational nodes need to be rotated out and
    that only healthy nodes should be rotated back in.
    """
    # should we make this node operational as the last step
    make_operational = force_operational

    if node and force_seamless:
        if not deployment.has_required_redundancy(node):
            if env.get('interactive', True):
                continue_anyway = prompt(
                    "\n\nNot possible to avoid service interruption to node "
                    "%s. Continue anyway? (Y/N)" % node
                )
                if continue_anyway != 'Y':
                    logger.critical(
                        "Node %s doesn't have required redundancy. "
                        "Aborting" % node
                    )
                    exit(1)
            else:
                logger.critical(
                    "Not possible to avoid service interruption to node %s",
                    node,
                )
                logger.critical(
                    "Deployment marked non-interactive. Aborting.")
                exit(1)

    # If the node is currently operational, we need to rotate it out of
    # operation
    if node and node.is_operational:
        # Remember to rotate it back in at the end
        make_operational = True
        logger.info("Making temporarily inoperative: %s", node)
        node.make_temporarily_inoperative()
        logger.info("Node %s now inoperative", node)

    yield

    if make_operational:
        logger.info("Restoring operation: %s", node)

        if node:
            opts = ['I', 'R', 'F']
            prompt_str = (
                "Node %s not made operational. Ignore/Retry/Fail (I/R/F)?"
            )
            auto_retries = 10
            count = 0
            while True:
                try:
                    node.make_operational()
                except Exception:
                    logger.warning(
                        "Failed to make node %s operational",
                        node,
                    )
                if node.is_operational:
                    logger.info("Node %s now operational", node)
                    return
                # It can take a few seconds for the load balancer to pick up
                # the instance
                logger.info("Waiting 1s for node to become operational")
                time.sleep(1)

                # Try one more time
                if node.is_operational:
                    logger.info("Node %s now operational", node)
                    return

                if count < auto_retries:
                    count += 1
                    logger.info("Still not operational. Trying again.")
                    continue

                logger.info("Node %s not operational.", node)
                logger.info(
                    "Health check URL: %s",
                    node.get_health_check_url(),
                )

                user_opt = None
                while not user_opt in opts:
                    user_opt = prompt(prompt_str % node)
                if user_opt == 'R':
                    continue
                elif user_opt == 'I':
                    return
                elif user_opt == 'F':
                    logger.critical(
                        "Node %s not healthy. Aborting deployment",
                        node,
                    )
                    exit(1)
            logger.info("Node %s now operational", node)
        else:
            # We made a new node with this step and we don't know which
            opts = ['I', 'R', 'F']
            prompt_str = "Active generation not fully operational. "
            prompt_str += "Ignore/Retry/Fail (I/R/F)?"

            while True:
                deployment.repair_active_generation(
                    force_operational=force_operational,
                    wait_until_operational=False)

                if deployment.active_is_fully_operational():
                    logger.info("Active generation is fully operational")
                    return

                user_opt = None
                while not user_opt in opts:
                    user_opt = prompt(prompt_str % node)
                if user_opt == 'R':
                    continue
                elif user_opt == 'I':
                    return
                elif user_opt == 'F':
                    logger.critical(
                        "Active generation not fully operational. Aborting")
                    exit(1)


def _prompt_for_seed_verification(deployer):
    opts = ['Yes', 'No']
    prompt_str = (
        "Requiring seed data verification. Node %s-%s WILL be affected "
        "Continue? (%s)?")
    user_opt = None
    while not user_opt in opts:
        context = (
            deployer.seed_deployment,
            deployer.seed_node_name,
            '/'.join(opts)
        )
        user_opt = prompt(prompt_str % context)
    if user_opt != 'Yes':
        logger.critical(
            "Node %s-%s would be affected. Aborting deployment",
            deployer.seed_deployment,
            deployer.seed_node_name)
        exit(1)
