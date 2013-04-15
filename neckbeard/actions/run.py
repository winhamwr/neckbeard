
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
