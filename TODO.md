## Parse and validate configuration

* Generate the environment.constants context
* Generate the environment.secrets context
* Mock out the node context with a magic backend for getting that info
* Generate the seed_environment context
* Output a NeckbeardConfiguration object and spit out JSON for nodes

## Use the Neckbeard config to run existing PolicyStat stuff

* Create a CLI that wraps Fabric
* Hook in to the config loading
* Figure out how to register provisioners
* Update the existing PolicyStat stuff to not expect `env.FOO` for all the configs

## Abstract out the Coordinator/SimpleDB backend

* Find a good interface
* Write a local JSON text file version

## Improve config validation and generation

* Add a CLI for creating and configuring at least one Django hello world
  template. Two web + Memcached nodes in 2 AZ's, RDS.
* Before any command can run, do more in-depth validation:
  * Validate the secrets.json and secrets.tpl.json relationship
  * Validate required fields for node_templates (ec2, rds, elb)
  * Validate required fields environments
  * Validate that environment nodes using templates override required_overrides

## "Neckbeard Service"-ize the PolicyStat stuff

* Take all of the PolicyStat-specific stuff and abstract it in to a series of plugins
* Many should be Neckbeard core, but some will live elsewhere
* ENVIRONMENT-ize the config
* Handle terrarium and pip requirements generically
* Use [Stevedor](http://stevedore.readthedocs.org/)
* Plugin interface? Config validation?
* Add a config to define which ENVIRONMENT variables your app expects


## Secrets

* NeckbeardLoader grows a SecretsManager to handle PGP both directions
* What about situations where developers should only have access to certain
  environments? Maybe use a secrets folder with a separate pgp file per
  environment and then a file that maps developer names to PGP public keys
  lists which developers should have access to which environment.

## Get a hello world example working with a tutorial

## Get a multi-server Django CMS example working with a tutorial

## Define the Chef-ized "Neckbeard Service" interface

* Gets the core Neckbeard config, the normal context and a specific section of
  the "services" config
* Uses hooks to do other things in the deployment lifecycle
* Defines cookbooks to pull in (source control or from opscode). Requires
  strict versioning
* Writes out chef-solo roles files and databag files for littlechef usage
* Declares which roles and databags it touches. Maybe has to list compatibility
  with other Neckbeard Services?
* Declares the ENVIRONMENT variables that it exposes (detect conflicts)

## Use littlechef

## Figure out how to pull in Chef plugins when needed

## Chef-ize all of the PolicyStat thing

## Write a guide on creating a "Neckbeard Service"

## Handle AMI creation and registering

* Use a locally-written JSON file for AMI ids and EBS snapshot ids

## Use Heroku [Buildpack](https://devcenter.heroku.com/articles/buildpack-api) to run the app

* All ENVIRONMENT config is rough for uwsgi. Can it be mixed?
* What about putting Nginx in front as a reverse-proxy? This is super-useful to
  guard against slow clients. Perhaps just a single config?

## Manage backups via a coordinator

* EBS snapshots
* RDS snapshots
* MySQL dump files?

## S3-bundle-based deploys

* Bundle up the whole environment and push it to S3 for deploys (can start it
  first and run it in the background while doing other stuff before you get to
  provisioning nodes)
* Modify Littlechef so that it pulls down the environment from S3
* Use another coordinator to log deploys and point to their bundle

## Support scaling node counts up/down via `scaling_group`

Add neckbeard commands to alter the number of nodes in a given `scaling_group`
and to view the number of nodes
  * Will require a separate coordinator for "Deployment Environment Variables"
    or something. Think Heroku-style config management.
  * Change the node coordinator schema so that there are both types of nodes,
    unique counter for node based on the type, and a unique name of a node. Eg.
    type: dyno0, name dyno0-00, number 00 and type: app0, name: app0, number 00
 * Changing the number of nodes down pulls nodes out of operation (services
   will need a hook to handle this: eg stopping celery workers). If pulling
   them out of operation fails, changing the numbers but leaving the same will
   retry.
 * Increasing the number of nodes doesn't take affect until the next deploy.
   What can we do to make that next deploy really fast?
 * `view` now displays the counts, highlights if the count is higher than
   current reality, highlights if there are still running out-of-operation
   nodes, makes a big deal if there are still running in-operation nodes that
   shouldn't be there

## Management for degraded nodes

### Interactive single-node mark-terminated

Sometimes, a node is degraded and we need to stop deploying to it, but either
can't terminate it via the GUI, or don't yet want to.

Support terminating specific nodes with an interactive command. Should list
options and let you hit a corresponding number.

### Add the ability to mark a node as "degraded"

When a node is degraded, `up` should spin up a replacement, but should keep the
current node around until it's ready to be replaced. This will simplify the
process of replacing nodes with minimal reduced-redundancy.

## Add a coordinator for recording deploys

* Stores things like time, result, command, deployer, path to the bundle, environment
* Ideally, allows locking and can help clients do queing

## Find a sane log-management strategy

* Find a tool to at least management the app's output
* Define an API for different routers and collectors so that folks can mix and match
  * [logplex](https://github.com/heroku/logplex)
  * [fluentd](https://github.com/fluent/fluentd)
  * loggly
  * splunk
  * logstash

## Con someone in to writing MySQL and PostgreSQL services

* It'd be super-sweet if they could do replication and HA also

## Make [admin processes](http://www.12factor.net/admin-processes) easy

* Fabric supports interactivity! Hooray!

## Use Apache Zookeeper to make configuration responsive

* All of the nodes should run zookeeper
* Zookeeper for pull-based High Availability (a memcached node goes down and
  configs update without requiring another deploy)
* Makes failover for redis, mysql, etc etc possible without manual intervention
