## Parse and validate configuration

* NeckbeardLoader object that takes a path to a .neckbeard directory
  * Rounds up the various JSON files
  * Parses them as JSON
  * Validates matching `node_aws_type`, `node_template_name` to files
  * Creates a Neckbeard object by passing in the validated JSON files
  * Tests:
    * Missing required files
    * Not matching required name fields according to dir structure
* Neckbeard CLI invocation to hook in to NeckbeardLoader
* Validate the secrets.json and secrets.tpl.json relationship
* Validate required fields for node_templates (ec2, rds, elb)
* Validate required fields environments
* Validate that environment nodes using templates override required_overrides
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

* Don't really want to use gunicorn, though. Do we want to ditch `Procfile`?
  Trade-off is being language agnostic versus having uwsgi magic.
* What about putting Nginx in front as a reverse-proxy? This is super-useful to
  guard against slow clients.

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
