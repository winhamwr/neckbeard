import logging

from fabric.api import env

from neckbeard.actions.utils import _get_gen_target, ACTIVE
from neckbeard.environment_manager import Deployment

logger = logging.getLogger('actions.view')


def view(environment_name, configuration, resource_tracker, generation=ACTIVE):
    """
    The view task output status information about all of the cloud resources
    associated with a specific generation of a specific deployment.
    """
    # Hard-coding everything to work on active for now
    env._active_gen = True
    generation_target = _get_gen_target()

    logger.info("Gathering deployment status")
    deployment = Deployment(
        environment_name,
        configuration.get('ec2', {}),
        configuration.get('rds', {}),
        configuration.get('elb', {}),
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
