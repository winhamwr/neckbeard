Neckbeard- Django deployment for the rest of us
===============================================

Neckbeard is your own personal operations team
in charge of maintaining your own personal PaaS.
It's the Heroku experience for developers
(dead-simple deploys)
combined with the flexibility of open source software
on servers that you control.
You get smart, fault-tolerant, repeatable, datacenter-aware, cloud-centric,
one-command deploys, without needing to spend the next month stringing together
tutorials.

If you're Netflix, Google, Facebook, LinkedIn, Twitter, etc,
then you have a team of folks who have already solved this problem for you.
If you just want to throw a hobby app up on a free PaaS, use Heroku.
If you have good reasons not to use a PaaS, then don't go re-invent the wheel.
Use Neckbeard.
::

    $ neckbeard up
    
Video Introduction
------------------

Like videos?
We have em: `Pycon Neckbeard Lightning Talk <http://youtu.be/OL3De8BAhME>`_

This talk mostly covers the reason why Neckbeard needs to exist.

Cloud-Native
------------

Neckbeard is built from the ground up for cloud-based ephemeral servers
that you can rebuild on a whim with one command.
It knows about your backups
and knows how to spin up test/staging environments from those backups
(and then spin them down).
The process you go through for disaster recovery
becomes just another deploy
because you do it all the time.
You can be confident that
you can rebuild your entire infrastructure with
a source code checkout,
a backup (probably also in the cloud somewhere),
a network connection
and some authentication credentials.

Repeatable
----------

Neckbeard encourages and empowers you to use existing configuration management
tools to handle the on-server heavy lifting (like ``Chef``, ``Puppet`` or
``SaltStack``).
This allows you to use simple, declarative, grokkable configuration files
to idempotently define your stack,
with a one-command front-end to Make It So.
Not only does this make your servers consistent,
but it means you can use ``Vagrant``
for consistent local development machine setup.

Extendable
----------

PaaS providers like Heroku and dotCloud do an amazing job
of providing simplicity for the simple case,
and that's the hallmark of a good tool.
We have the same goal,
but we also realize that the ability to evolve as complexity increases
is an absolute requirement for mission-critical operations.
That's why we favor:

 * Explicit configuration over implicit magic
 * Pluggable backends everywhere
 * An architecture based on build blocks of customizable ``Service Addons``

Current Status
--------------

Neckbeard was publicly announced at PyCon 2013 in a lightning talk. It is not currently usable,
but is looking for beta testers
who are willing to communicate their deployment setup (nothing private)
in exchange for assistance in getting their configuration created.
Beta testers should be interested in deploying a python application to AWS.

The current path to a usable beta is:

 * Define a configuration format (mostly done, but feedback welcome)
 * Bring in the existing codebase from PolicyStat's internal deploy tool as a
   starting point.
 * Get a "hello world" python application running with a tutorial.
 * Make abstractions and plugin-ize the existing code.
 * Write guides for writing backends to alternative clouds (Rackspace)
 * Write guides for writing and using additional ``Service Addons``

Get in Touch
------------

Have a question or comment about using, improving or extending Neckbeard?
Get in touch!

Forums: https://groups.google.com/d/forum/neckbeard
IRC: #neckbeard on freenode
