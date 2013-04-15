from __future__ import with_statement

import copy
import httplib
import json
import logging
import os.path
import requests
import time
import urllib
from collections import namedtuple
from datetime import datetime, timedelta
# Using the decorator libs contextmanager because it allows contextmanagers to
# be used as decorators
# See: http://micheles.googlecode.com/hg/decorator/documentation.html#id11
from decorator import contextmanager
from requests.exceptions import RequestException

git = None
try:
    import git
except ImportError:
    # Git is only required for certain commands
    pass

from fabric.api import env, require, prompt, local, task
try:
    import pynotify
    DT_NOTIFY = True
except ImportError:
    DT_NOTIFY = False

from pstat.pstat_deploy import fab_out_opts
from pstat.pstat_deploy.generations import (
    Deployment,
    InfrastructureNode,
)
from pstat.pstat_deploy.deployers.ec2 import Ec2NodeDeployment
from pstat.pstat_deploy.deployers.rds import RdsNodeDeployment

logger = logging.getLogger('status_actions')
time_logger = logging.getLogger('timer')

deploy_timers = {}

fab_output_hides = fab_out_opts[logger.getEffectiveLevel()]
fab_quiet = fab_output_hides + ['stderr']

linked_dirs = ['user_media']

LOG_DIR = '/var/log/pstat'

GITHUB_COMPARE_URL = 'https://github.com/PolicyStat/PolicyStat/compare/%s'
NEWRELIC_API_HTTP_HOST = 'rpm.newrelic.com'
NEWRELIC_API_HTTP_URL = '/deployments.xml'
PAGERDUTY_SCHEDULE_URL = 'https://%(project_subdomain)s.pagerduty.com/api/v1/schedules/%(schedule_key)s/overrides'  # noqa
HIPCHAT_MSG_API_ENDPOINT = "https://api.hipchat.com/v1/rooms/message"

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
REPAIR_START_MSG = (
    '%(deployer)s <strong>Repairing</strong> '
    '<em>%(deployment_name)s</em>'
)
REPAIR_END_MSG = (
    '%(deployer)s <strong>Repaired</strong> '
    '<em>%(deployment_name)s</em>'
    "<br />Took: <strong>%(duration)s</strong>s"
)
INCREMENT_START_MSG = (
    '%(deployer)s <strong>Incrementing</strong> '
    '<em>%(deployment_name)s</em>'
)
INCREMENT_END_MSG = (
    '%(deployer)s <strong>Incremented</strong> '
    '<em>%(deployment_name)s</em>'
    "<br />Took: <strong>%(duration)s</strong>s"
)
TERMINATE_START_MSG = (
    '%(deployer)s <strong>Terminating</strong> '
    '<em>%(deployment_name)s</em> %(generation)s'
)
TERMINATE_END_MSG = (
    '%(deployer)s <strong>Terminated</strong> '
    '<em>%(deployment_name)s</em> %(generation)s'
    "<br />Took: <strong>%(duration)s</strong>s"
)


def get_deployer():
    return os.environ.get(
        'POLICYSTAT_DEPLOYER_NAME',
        os.environ.get('USER', 'unknown'),
    )


@contextmanager
def notifies_hipchat(start_msg, end_msg):
    """
    A decorator to post a notification to hipchat at the start and end of this
    function.

    The `FOO_msg` arguments define template strings that can use the
    following variables as context:

    * `deployer` The deploying user
    * `deployment_name` The deploying environment. Eg. "beta"
    * `generation` The generational target. Eg. "live", "pending"
    * `git_branch` The current git branch name.
    * `duration` The number of wall-clock seconds taken to complete the
      decorated method. Note: Only available to `end_msg`.
    """
    # Ensure we have the required configs
    hipchat_conf = {}
    for key in ['api_token', 'room']:
        hipchat_conf[key] = env.get('hipchat_%s' % key, None)
    for key, value in hipchat_conf.items():
        if value is None:
            logger.warning(
                "No hipchat_%s found. Not notifying.",
                key,
            )
            yield
            logger.warning(
                "No hipchat_%s found. Not notifying.",
                key,
            )
            return
    hipchat_conf['color'] = env.get('hipchat_color', 'green')
    hipchat_conf['from'] = env.get('hipchat_from', 'Neckbeard')

    # Get our git branchname. Fallback to a SHA if detached head
    r = git.Repo('.')
    branch_name = r.commit().hexsha[:7]
    if not r.head.is_detached:
        branch_name = r.active_branch.name

    # Build the message
    context = {
        'deployer': get_deployer(),
        'deployment_name': env.get('_deployment_name', 'unknown'),
        'generation': _get_gen_target().lower(),
        'git_branch': branch_name,
    }
    message = start_msg % context

    _send_hipchat_msg(message, hipchat_conf)

    method_start = datetime.now()
    yield
    duration = datetime.now() - method_start

    context['duration'] = duration.seconds
    message = end_msg % context

    _send_hipchat_msg(message, hipchat_conf)


def _send_hipchat_msg(message, hipchat_conf):
    params = {
        'auth_token': hipchat_conf['api_token'],
        'room_id': hipchat_conf['room'],
        'color': hipchat_conf['color'],
        'from': hipchat_conf['from'],
        'message': message,
    }
    try:
        response = requests.post(
            HIPCHAT_MSG_API_ENDPOINT,
            params=params,
            timeout=5,
        )
    except RequestException, e:
        logger.warning("Failed to post message to hipchat")
        logger.warning("Error: %s", e)
        return

    if response.status_code != requests.codes.ok:
        logger.warning(
            "Bad status code posting message to hipchat: %s",
            response.status_code,
        )
        logger.warning("Response content: %s", response.text)


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


@contextmanager
def prompt_on_exception(msg):
    try:
        yield
    except Exception, e:
        logger.warning(msg)
        logger.warning("Exception thrown: %s", e)

        continue_choice = 'C'
        abort_choice = 'A'
        opts = [continue_choice, abort_choice]
        prompt_str = "[C]ontinue the deploy or [A]bort?"
        user_opt = None
        while not user_opt in opts:
            user_opt = prompt(prompt_str)

        if user_opt == abort_choice:
            logger.critical("Aborting deploy")
            exit(1)
        logger.warning("Continuing, despite error")


@contextmanager
def logs_duration(timer_name='Total', output_result=False):
    """
    A decorator to output the duration of the function after completion.
    """
    start_time = datetime.now()
    try:
        yield
    finally:
        duration = datetime.now() - start_time
        deploy_timers[timer_name] = duration.seconds
        if output_result:
            time_logger.info("%02ds- %s", duration.seconds, timer_name)


@task
@notifies_hipchat(start_msg=TERMINATE_START_MSG, end_msg=TERMINATE_END_MSG)
def terminate(soft=None):
    require('_deployment_name')
    require('_deployment_confs')

    while soft not in ['H', 'S']:
        soft = prompt("Hard (permanent) or soft termination? (H/S)")

    soft_terminate = bool(soft == 'S')

    generation_target = _get_gen_target()
    if generation_target == 'ACTIVE':
        logger.critical("Can't terminate active generation")
        exit(1)

    if soft_terminate:
        logger.info(
            "SOFT terminating %s nodes." % generation_target)
        logger.info("They will be removed from operation, but not terminated")
    else:
        logger.info(
            "HARD terminating %s nodes." % generation_target)
        logger.info("They will be TERMINATED. This is not reversible")

    deployment = Deployment(
        env._deployment_name,
        env._deployment_confs['ec2'],
        env._deployment_confs['rds'],
        env._deployment_confs['elb'],
    )

    if generation_target == 'PENDING':
        possible_nodes = deployment.get_all_pending_nodes(is_running=1)
    else:
        # OLD
        possible_nodes = deployment.get_all_old_nodes(is_running=1)

    # Filter out the nodes whose termination isn't yet known
    # This is an optimization versus just calling `verify_deployment_state`
    # directly, since we need the nodes afterwards anyway.
    logger.info("Verifying run statuses")
    for node in possible_nodes:
        node.verify_running_state()

    running_nodes = [node for node in possible_nodes if node.is_running]

    if not running_nodes:
        logger.info(
            "No running nodes exist for generation: %s",
            generation_target,
        )
        return

    # Print the nodes we're going to terminate
    for node in running_nodes:
        logger.info("Terminating: %s", node)

    confirm = ''
    while not confirm in ['Y', 'N']:
        confirm = prompt(
            "Are you sure you want to TERMINATE these nodes? (Y/N)")
    if confirm == 'N':
        exit(1)

    for node in running_nodes:
        node.make_fully_inoperative()
        if soft_terminate:
            # If we're doing a soft terminate, disable newrelic monitoring
            # A hard terminate takes the instance down completely
            node.newrelic_disable()
        else:
            node.terminate()


@task
def view():
    require('_deployment_name')
    require('_deployment_confs')

    generation_target = _get_gen_target()

    logger.info("Gathering deployment status")
    deployment = Deployment(
        env._deployment_name,
        env._deployment_confs['ec2'],
        env._deployment_confs['rds'],
        env._deployment_confs['elb'],
    )
    deployment.verify_deployment_state()

    logger.info("Gathering nodes")
    if generation_target == 'ACTIVE':
        nodes = deployment.get_all_active_nodes()
    elif generation_target == 'PENDING':
        nodes = deployment.get_all_pending_nodes()
    else:
        nodes = deployment.get_all_old_nodes(is_running=1)

    ec2_nodes = []
    rds_nodes = []
    for node in nodes:
        if node.aws_type == 'ec2':
            ec2_nodes.append(node)
        elif node.aws_type == 'rds':
            rds_nodes.append(node)

    # Generation output
    gen_id = None
    if generation_target == 'PENDING':
        gen_id = deployment.pending_gen_id
    else:
        gen_id = deployment.active_gen_id

    if gen_id:
        if generation_target == 'OLD':
            print "%s generation: older than %s\n" % (
                generation_target,
                gen_id,
            )
        else:
            print "%s generation: %s\n" % (generation_target, gen_id)
    else:
        print "No %s generation found\n" % generation_target

    # Ec2 output
    ec2_nodes.sort(key=lambda x: x.is_running)
    print "===%s EC2 Node(s)===" % len(ec2_nodes)
    if len(ec2_nodes) == 0:
        print "No configured nodes"
    else:
        for node in ec2_nodes:
            print "%s" % node.get_status_output()
    print ""

    # RDS output
    rds_nodes.sort(key=lambda x: x.is_running)
    print "===%s RDS Node(s)===" % len(rds_nodes)
    if len(rds_nodes) == 0:
        print "No configured nodes"
    else:
        for node in rds_nodes:
            print "%s" % node.get_status_output()


@task
def override():
    """
    Manually fix the generational config for the given generation.

    This is required for initial setup of the generational system. We are only
    modifying the simpledb records of the instances, not the instances
    themselves.
    """
    require('_deployment_name')
    require('_deployment_confs')

    generation_target = _get_gen_target()

    deployment = Deployment(
        env._deployment_name,
        env._deployment_confs['ec2'],
        env._deployment_confs['rds'],
        env._deployment_confs['elb'],
    )
    deployment.verify_deployment_state()

    if generation_target not in ['ACTIVE', 'PENDING']:
        exit(1)

    opts = ['Y', 'N']
    for aws_type, confs in env._deployment_confs.items():
        for node_name, node_confs in confs.items():
            if generation_target == 'ACTIVE':
                node = deployment.get_active_node(aws_type, node_name)
            else:
                node = deployment.get_pending_node(aws_type, node_name)

            if node:
                print "Existing node found for %s: %s\n" % (node_name, node)
                replace_node = ''
                while replace_node not in opts:
                    replace_node = prompt("Change this node? (Y/N)")
                if replace_node == 'N':
                    continue
            else:
                print "No node for %s: %s\n" % (aws_type, node_name)

            retire_alter_opts = ['Retire', 'Alter']
            retire_alter_response = ''
            should_alter_node = False
            should_retire_node = False

            while retire_alter_response not in retire_alter_opts:
                retire_alter_response = prompt(
                    "Retire or Alter node? (Retire/Alter)")
            if retire_alter_response == 'Retire':
                should_retire_node = True
            else:
                should_alter_node = True

            if should_alter_node:
                # Prompt if the node doesn't already exist
                if not node:
                    add_node = ''
                    while add_node not in opts:
                        add_node = prompt(
                            'No node record found for <%s>-%s. Add one? '
                            '(Y/N)' % (aws_type, node_name)
                        )
                    if add_node == 'N':
                        should_alter_node = False
            if should_retire_node and not node:
                logger.critical(
                    "No node record found. Can't retire a non-existent node.")
                continue

            if should_alter_node:
                _override_node(
                    node, deployment, aws_type, node_name)
            elif should_retire_node:
                logger.info("Retiring: %s", node)
                confirm = ''
                while confirm not in opts:
                    confirm = prompt(
                        "Are you sure you want to RETIRE this node? (Y/N)")
                if confirm == 'Y':
                    node.make_fully_inoperative()
                    node.retire()


def _override_node(node, deployment, aws_type, node_name):
    aws_id = prompt(
        "Enter the %s id for <%s>-%s:" % (aws_type, aws_type, node_name))
    if not node:
        node = InfrastructureNode()
        node.set_aws_conns(deployment.ec2conn, deployment.rdsconn)
        node.aws_type = aws_type

    node.aws_id = aws_id

    # Make sure this node actually exists on aws
    node.refresh_boto_instance()
    assert node.boto_instance

    node.generation_id = deployment.active_gen_id
    node.is_active_generation = 1
    if not node.generation_id:
        node.generation_id = deployment.pending_gen_id
        node.is_active_generation = 0
    node.deployment_name = deployment.deployment_name
    node.name = node_name
    node.creation_date = node.launch_time
    node.is_running = 1
    node.initial_deploy_complete = 1

    if not node.is_actually_running():
        print "ERROR: %s isn't actually running" % aws_id
        exit(1)
    node.save()
    logger.info("Node %s altered", node)


@task
@notifies_hipchat(start_msg=REPAIR_START_MSG, end_msg=REPAIR_END_MSG)
def repair(force='n'):
    """
    Ensure that all healthy active-generation nodes are operational.
    """
    require('_deployment_name')
    require('_deployment_confs')
    require('_active_gen')

    force = force == 'y'

    assert env._active_gen
    deployment = Deployment(
        env._deployment_name,
        env._deployment_confs['ec2'],
        env._deployment_confs['rds'],
        env._deployment_confs['elb'],
    )
    deployment.verify_deployment_state()

    activated_nodes = deployment.repair_active_generation(
        force_operational=force)

    if len(activated_nodes):
        logger.info("Succesfully made %s node(s) operational",
                    len(activated_nodes))
    else:
        logger.info("No nodes modified")


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


@task
def run():
    """
    Sets the env.hosts variable to contain all of the app servers in the
    appropriate generation and deployment.
    """
    require('_deployment_name')
    require('_deployment_confs')
    require('_active_gen')

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

    hosts = []
    for aws_type, node_confs in dep_confs:
        for node_name, conf_ in node_confs:
            if aws_type != 'ec2':
                continue

            if env._active_gen:
                node = deployment.get_active_node('ec2', node_name)
            else:
                node = deployment.get_pending_node('ec2', node_name)

            if (not node
                    or not node.boto_instance
                    or not node.boto_instance.public_dns_name):
                continue

            # Set the user value, only the last value holds
            conf_key = env._deployment_confs[aws_type][node_name]['conf_key']
            if 'user' in env.INSTANCES[conf_key]:
                env.user = env.INSTANCES[conf_key]['user']

            hosts.append(node.boto_instance.public_dns_name)

    env.hosts = hosts


def _is_tagged_version(repo):
    """
    Check that we are deploying from a tagged commit, and have no uncommitted
    changes.

    Return a boolean.
    """
    # Check that the tag is correct
    head_commit = repo.head.commit
    for tag in reversed(repo.tags):
        if tag.commit == head_commit:
            return True
    return False


def _is_unchanged_from_head(repo):
    # Check that there are no uncommitted changes.
    head_commit = repo.head.commit
    if head_commit.diff(None) != []:  # Diff HEAD commit versus working copy.
        return False
    return True


def _push_tags(repo):
    # Push tags if there is just a single remote.
    if len(repo.remotes) == 1:
        remote = repo.remotes[0]
        logger.info("Pushing tags for current git repository.")
        remote.push(tags=True)
    else:
        logger.warning(
            "Could not push tags, there are %d remotes." % len(repo.remotes))


def _get_git_repo(path='.'):
    if git is None:
        raise ImportError('This check requires GitPython to be installed.')

    try:
        repo = git.Repo(path)
    except git.InvalidGitRepositoryError:
        logger.critical('Not in a git repository.')
        exit(1)
    return repo


def _announce_deployment():
    newrelic_conf = env._deployment_confs['conf'].get('newrelic', {})
    if newrelic_conf.get('announce_deploy', False):
        _send_deployment_end_newrelic()


@task
def announce():
    require('_deployment_name')
    require('_deployment_confs')
    require('_active_gen')

    # Make sure we're in the git repo
    _get_git_repo()

    _announce_deployment()


@task
@notifies_hipchat(start_msg=UP_START_MSG, end_msg=UP_END_MSG)
@logs_duration(output_result=True)
def up(force='n'):
    """
    Make sure that the instances for the specified generation are running and
    have current code. Will update code and deploy new EC2 and RDS instances as
    needed.
    """
    require('_deployment_name')
    require('_deployment_confs')
    require('_active_gen')

    with logs_duration(timer_name='validation'):
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
    with logs_duration(timer_name='gather deployment state'):
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
    with logs_duration(timer_name='gather node status'):
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
    with logs_duration(timer_name='build deployers'):
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
    with logs_duration(timer_name='initial provision'):
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
    with logs_duration(timer_name='deploy rds'):
        for deployer in rds_deployers:
            deployer.run()

    logger.info("Determining EC2 node deploy priority")
    ec2_deployers = _order_ec2_deployers_by_priority(ec2_deployers)

    # Configure the EC2 nodes
    logger.info("Deploying to EC2 nodes")
    for env_confs, deployer in ec2_deployers:
        timer_name = '%s deploy' % deployer.node_name
        with logs_duration(timer_name='full %s' % timer_name):
            node = deployer.get_node()

            # Prepare the environment for deployment
            for key, value in env_confs.items():
                setattr(env, key, value)

            with seamless_modification(
                node,
                deployer.deployment,
                force_seamless=env._active_gen,
                force_operational=force):

                pre_deploy_time = datetime.now()
                with logs_duration(timer_name=timer_name, output_result=True):
                    deployer.run()
            if DT_NOTIFY:
                _send_deployment_done_desktop_notification(
                    pre_deploy_time, deployer)

    _announce_deployment()

    time_logger.info("Timing Breakdown:")
    sorted_timers = sorted(
        deploy_timers.items(),
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


def _get_gen_target():
    generation_target = ''
    if hasattr(env, '_active_gen'):
        if env._active_gen:
            generation_target = 'ACTIVE'
        else:
            if getattr(env, '_old_gen', False):
                generation_target = 'OLD'
            else:
                generation_target = 'PENDING'
    else:
        logger.critical("Must run active, pending or old before this task")
        exit(1)

    return generation_target


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


def _take_temporary_pagerduty(
        duration, api_key, user_id, project_subdomain, schedule_key):
    '''
    ``duration`` is the amount of seconds that the pagerduty user associated
    with the ``user_id`` will take over pagerduty at ``project_subdomain`` for
    the schedule associated with the ``schedule_key``. The ``api_key`` is
    needed for authentication and can be found at
    https://``project_subdomain``.pagerduty.com/api_keys.
    '''
    logger.info('Attempting Pagerduty override')

    # Set up headers
    headers = {
        'Content-type': 'application/json',
        'Authorization': 'Token token=%s' % api_key,
    }

    # Set up time start and end dates
    now = datetime.utcnow()
    later = now + timedelta(seconds=duration)
    # Using a trailing Z to indicate UTC time
    payload = {
        'override': {
            'user_id': '%s' % user_id,
            'start': '%sZ' % now.isoformat(),
            'end': '%sZ' % later.isoformat(),
        },
    }

    # Post to pagerduty to override whos on call.
    response = requests.post(
        PAGERDUTY_SCHEDULE_URL % {
            'project_subdomain': project_subdomain,
            'schedule_key': schedule_key,
        },
        data=json.dumps(payload),
        headers=headers,
    )

    # Alert the deployer if there is an error.
    if not response.ok:
        logger.error(
            'Pagerduty override failed status code: "%s".',
            response.status_code,
        )
        logger.error(
            'Error response output: "%s".',
            response.content,
        )
    else:
        logger.info('Pagerduty override has completed successfully.')


def _send_deployment_end_newrelic():
    '''
    API: https://rpm.newrelic.com/accounts/87516/applications/402046/deployments/instructions  # noqa
    '''
    GIT_MOST_RECENT_TWO_TAGS = 'git tag | tail -2'
    GIT_MOST_RECENT_COMMIT_MESSAGE = 'git log -1 --format="%s"'
    GIT_CURRENT_TAG = 'git describe --tags'
    GITHUB_COMPARE_OPERATOR = '...'
    NEWRELIC_API_HTTP_METHOD = 'POST'

    def generate_github_changelog_url(tags):
        return GITHUB_COMPARE_URL % GITHUB_COMPARE_OPERATOR.join(tags)

    if env.get('newrelic_api_token', False):
        logger.info('Announcing deployment to newrelic')
        headers = {
            'x-api-key': env.newrelic_api_token,
        }

        # Description is the generation target, e.g. active, pending
        description = '%s ' % (_get_gen_target().lower(),)
        params = {
            'deployment[application_id]': env.newrelic_application_id,
            'deployment[description]': description,
        }
        # Add user information to deployment
        user = get_deployer()
        if user:
            params['deployment[user]'] = user

        # Set the changelog to a github comparison URL
        result = local(GIT_MOST_RECENT_TWO_TAGS, capture=True)
        if result.return_code == 0:
            tags = result.split()
            url = generate_github_changelog_url(tags)
            params['deployment[changelog]'] = url

        # Append the most recent commit message to the description
        result = local(GIT_MOST_RECENT_COMMIT_MESSAGE, capture=True)
        if result.return_code == 0:
            params['deployment[description]'] += result.strip()

        # Set the revision to the current tag
        result = local(GIT_CURRENT_TAG, capture=True)
        if result.return_code == 0:
            params['deployment[revision]'] = result.strip()

        # Attempt to post the deployment to newrelic
        conn = httplib.HTTPSConnection(NEWRELIC_API_HTTP_HOST)
        conn.request(NEWRELIC_API_HTTP_METHOD, NEWRELIC_API_HTTP_URL,
            urllib.urlencode(params), headers,
        )
        response = conn.getresponse()
        if response.status != 201:
            logger.warn('Failed to post deployment to newrelic')


def _send_deployment_done_desktop_notification(pre_deploy_time, deployer):
    if not DT_NOTIFY:
        return
    title = "%(deployment)s %(target)s %(node_name)s deployed"
    content = "Took %(seconds)s seconds"
    time_diff = datetime.now() - pre_deploy_time
    context = {
        'deployment': env._deployment_name,
        'target': _get_gen_target().lower(),
        'node_name': deployer.node_name,
        'seconds': time_diff.seconds,
    }

    notification = pynotify.Notification(title % context, content % context)
    notification.show()
