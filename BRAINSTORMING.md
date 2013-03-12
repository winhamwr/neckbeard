
# Core things

* Tracking arbitrary cloud resources (ec2 nodes, rds nodes)- Extensible
* Tracking environments (production/staging)- Core
* Tracking and incrementing generations (active/pending/old)- Core
* Launching cloud resources and seeding them with data- Extensible
* Determining resource health and operational status- Extensible
* Defining packagers to slug-up the proprietary app code with its requirements- Extensible
* A Neckbeard Stack that knows how to take the slug from a packager and run it- Core
* Load balancing
* Defining backing services via chef-solo roles and distributing them to appropriate cloud resources- Core (Service definitions are Extensible)
* Configure hierarchy of deep-merged parameters for node- Core: type -> size -> environment -> availability zone
* Availability-zone-aware high availability targets, under which you can't scale- Extensible

# Neckbeard Components

## CLI

The `neckbeard` command installed as a normal python package.

## Core Configs

# Neckbeard-compatible app components

## ./neckbeard/config.yml

Defines:

* Chosen App Packager and its configs
* Chosen Coordinator its configs
* Neckbeard Stack and its configs
* Additional backing services and their configs
* Node types (ec2 instance sizes, services on those nodes)
* Base environments
  * See next section for what they define.
  * Actual environments can extend these to only define differences

## ./neckbeard/envs/<name>.yml

eg. `./neckbeard/envs/production.yml`

* The optional base environment from which to extend
*
# Neckbeard Coordinator

This is Neckbeard's memory of previous deployments.
It contains the shared state
that lets you tell one ec2 node from another
and mix projects/environments
within one AWS acccount.

### Uses

The Coordinator is used to:

* Find existing nodes of certain types
* Track environments
* Track generations
* Manage the shared configuration environment (including scaling processes)
* Manage backing services.

### Data

The Coordinator records:

* A locking/coordination mechanism to prevent concurrent modifications.
* A deployment action audit trail.
* Each

### Included Coordinator Backends

Neckbeard ships with 3 different backends from which to choose.
It's also possible to write a Coordinator backend
against an arbitrary datastore/service
(Dynamo, MySQL, Zookeeper)
by implementing the Coordinator Backend interface.

#### Local YAML

Your data is stored locally via a set of local YAML files.
For one-person development,
you can check these in to version control
or use your favorite backup utility (Dropbox?)
for no-fuss coordination.
Atomicity of coordination isn't supported.

#### YAML + S3

Same as the local YAML option,
except this backend automatically synchronizes the files
to Amazon S3.
Atomicity of coordination isn't supported.

#### SimpleDB

For distributed teams,
this provides high-performance coordination
with the added benefit of atomic operations.
In the case of multiple team members with the ability to deploy,
this atomicity ensures that folks can't
accidentally make concurrent modifications
to the same environment.

Optionally,
the SimpleDB backend also writes out local YAML files
as a disaster recovery mechanism.
