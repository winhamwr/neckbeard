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

## Plugin-ize the PolicyStat stuff

* Take all of the PolicyStat-specific stuff and abstract it in to a series of plugins
* Many should be Neckbeard core, but some will live elsewhere
* ENVIRONMENT-ize the config
* Handle terrarium and pip requirements generically
* Use [Stevedor](http://stevedore.readthedocs.org/)
* Plugin interface? Config validation?

## Abstract out the Coordinator/SimpleDB backend

* Find a good interface
* Write a local JSON text file version

* NeckbeardLoader grows a SecretsManager to handle PGP both directions

