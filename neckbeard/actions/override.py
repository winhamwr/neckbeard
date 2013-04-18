import logging

from fabric.api import env, task, require, prompt

from neckbeard.actions.utils import _get_gen_target
from neckbeard.cloud_resource import InfrastructureNode
from neckbeard.environment_manager import Deployment

logger = logging.getLogger('actions.override')


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
