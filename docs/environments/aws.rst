=======================================
Configuration Options for AWS Resources
=======================================

Elastic Compute Cloud (EC2)
===========================

Required Options
----------------

`aws.keypair`
~~~~~~~~~~~~~

The keypair the EC2 instance will be launched with.

Optional Configuration
----------------------

`aws.elastic_ip`
~~~~~~~~~~~~~~~~

An elastic IP to assign to this instance when it's made operational.

A common pattern for assigning elastic IPs in combination with scaling is to
build a dictionary in `constants` that you subsequently reference in a
`node_template` or `environment` configuration.

For example, if I have an `environment` with two scaling groups that can scale
to up to 4 instances each, I could set up a `constants` config like:

    neckbeard_conf_version: "0.1"
    environments:
        test:
            aws:
                elastic_ips:
                    app0:
                        - 127.0.0.1
                        - 127.0.0.2
                        - 127.0.0.3
                        - 127.0.0.4
                    app1:
                        - 127.0.0.5
                        - 127.0.0.6
                        - 127.0.0.7
                        - 127.0.0.8

And then my `environment` configuration would look something like:

    name: test
    neckbeard_conf_version: "0.1"
    aws_nodes:
        ec2:
            app0:
                name: app0
                scaling:
                    minimum: 1
                    maximum: 4
                aws:
                    availability_zone: us-east-1b
                    elastic_ip: {{ environment.constants.aws.elastic_ips[node.name][node.scaling_index] }}
                    keypair: test
            app1:
                name: app1
                scaling:
                    minimum: 1
                    maximum: 4
                aws:
                    availability_zone: us-east-1c
                    elastic_ip: {{ environment.constants.aws.elastic_ips[node.name][node.scaling_index] }}
                    keypair: test


Relational Database Service (RDS)
=================================

Required Options
----------------

`foo.baz`
~~~~~~~~~

Optional Configuration
----------------------

`foo.baz`
~~~~~~~~~

Elastic Load Balancer (ELB)
===========================

Required Options
----------------

`foo.baz`
~~~~~~~~~

Optional Configuration
----------------------

`foo.baz`
~~~~~~~~~




