Getting Started
===============

The easiest way to get started is to run::

    $ neckbeard init

From the root of your project's source repo and follow the interactive prompts.
It will help you create the appropriate config files, roughly following this
process:

1. Define your AWS credentials in ``~/.neckbeard/auth.yml``
2. Create a ``Procfile`` in your project root that defines how Neckbeard will
   run your processes.
3. Create a ``neckbeard.yml`` file to define:

    * Where your ``pip`` requirements files live, so we can create a virtualenv.
    * What additional services your app requires (mysql, memcached, rabbitmq)
    * How many different neckbeard ``Environments`` you need (production, staging, etc)

Next, tell Neckbeard how it should access the AWS API::

    $ neckbeard login

You'll be access for you AWS credentials
and a label for those credentials
(production, dev, staging, etc.).

In the advanced getting started, you can see how to customize your environment
and tweak your high availability guarantees.

The How
-------

Getting Started Advanced
------------------------

1. Defining AWS Credentials in ``~/.neckbeard/auth.yml``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Turns out, if you want to do stuff in the cloud, you need to pay someone. Step
0 is to get yourself an AWS account. Step 1 is create a
``~/.neckbeard/auth.yml`` file that looks something like this::

    development:
        aws_access_key: AAAAAAAAAAAAAA
        aws_secret_key: AAAAAAAAAAAAAA
    production:
        aws_access_key: BBBBBBBBBBBBBB
        aws_secret_key: BBBBBBBBBBBBBB

If you likee the gui, you can just run ``$ neckbeard login``.

This is likely to be the only neckbeard file that you don't keep under source
control. It's a simple yaml configuration file containing named sets of AWS
access credentials (``development`` and ``production`` in this case). You don't
need multiple sets of credentials, but it can make it easier to control access
and ensure absolute separation of your production environment.

2. Create your ``Procfile``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

TODO: Heroku-style procfiles

3. Configure your services
~~~~~~~~~~~~~~~~~~~~~~~~~~

1. You can also customize your infrastructure topology by creating server
   "roles." These are just a mapping of a name to a set of services so you can
   customize what lives on the same/separate nodes.
2. It's also possible to customize the level of high availability for each
   environment. For example, you can say that your production environment
   always needs at least one healthy member of each role in two different
   availability zones, but the development environment only needs one
   availability zone.

3. Configure application settings in

Neckbeard Architecture
----------------------

Neckbeard consists of several components
glued together at well-defined interfaces.

Neckbeard Runtime Stack
~~~~~~~~~~~~~~~~~~~~~~~

The Neckbeard runtime stack
is very similar to `Heroku's Cedar Stack`_ in goal.
It aims to follow the `twelve-factor app`_ principles,
providing for app portability, maintainability and scalability.
The current stack is called Bacon.

The stack consists of an OS
(Ubuntu Server Linux 10.04),
plus a collection of Chef cookbooks and roles
for defining how services and process
run and interact.
A developer deploying their app
does not have to think on this low of a level.
Experts, however,
can make changes here to gain fine-grained control.

.. _`Heroku's Cedar Stack`: https://devcenter.heroku.com/articles/cedar
.. _`twelve-factor app`: http://www.12factor.net/

Provisioners
~~~~~~~~~~~~

A ``Provisioner`` is responsible for
taking already-existing nodes
or backing services
and making them conform to the runtime stack's configuration.
This usually means running Chef on the machine,
making API calls,
and pushing application source code.
``Provisioners`` only deal with one node at a time.

Deployers
~~~~~~~~~

A ``Deployer`` is responsible for managing the creation/status
for a certain type of node or backing service
(ec2, RDS, ELB, New Relic, S3, etc).
If something is supposed to exist and doesn't,
then the ``Deployer`` is responsible for creating it
and configuring things like EBS volumes and Elastic IPs.
The actual configuration of the node
is then passed off to a ``Provisioner``.

Generational Deployment Manager
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Neckbeard is a generational deployment system.
That means that it's easy to spin up fresh versions of your entire stack
with one command and then switch in that new version.
Neckbeard will handle gathering up your data,
spinning up any required resources,
putting the data on those nodes,
and then configuring those nodes to work together.

This CLI interface and library are
responsible for actually making state changes to your deployment.
Boto is used to interact with AWS,
Fabric runs commands against instances,
and SimpleDB is used as a datastore
for all of the node information.

Neckbeard Configuration Files
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

These are the high-level files
you use to tell Neckbeard how to launch your app.
This consists of:

1. ``~/.neckbeard/auth.yml``: Holds AWS authentication credentials.

2. ``Procfile`` in your app root
defines the processes that need to exist
(application servers, celery workers, etc.)

3. ``neckbeard.yml`` Configures all other aspects of neckbeard
including where your pip requirements files are,
environment-specific settings,
etc.

Neckbeard CLI
~~~~~~~~~~~~~

The Neckbeard command line interface
is where the rubber meets the road.


