
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

