Part 1: Minimal Deployment
==========================

Clone Django-CMS or some such
-----------------------------

Install Neckbeard
-----------------

Sign up for AWS
---------------

Initial Neckbeard Configuration
-------------------------------

Resource Tracker
~~~~~~~~~~~~~~~~

Deployment Template
~~~~~~~~~~~~~~~~~~~

Beta environment
 * ELB
 * 2 small ec2 instances
 * RDS

Secrets
~~~~~~~

Deploy
------

Part 2: Add Celery
==================

Add Celery config to existing resources
---------------------------------------

Deploy
------

Add new Celery-specific resources
---------------------------------

Deploy
------

Part 3: Add a Production environment
====================================

Copy the beta config
--------------------

Different secrets and constants
-------------------------------

Deploy
------

Change beta to not use separate Celery resources
------------------------------------------------

Deploy
------

Part 4: Node Templates for DRY magic
====================================

Define RDS Node Template
------------------------

Use that for Beta and Production
--------------------------------

Deploy
------

Define Celery-dedicated Node Template
-------------------------------------

Define no-Celery Node Template
------------------------------

Define shared-Celery Node Template
----------------------------------

Deploy
------

Part 5: Building Brain Wrinkles: Pure Python
============================================

Walk through building Pagerduty wrinkle.

Part 6: Building Brain Wrinkles: Chef
=====================================

Walk through building Redis? wrinkle.

Part 7: Tips for porting existing deploy
========================================

Tips for Fabric-based deploys
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Part 8: Building AMIs for speedy launch
=======================================

Part 9: Scaling resources with Scaling Managers
===============================================

Manual Scaling
~~~~~~~~~~~~~~

Dynamic Scaling
~~~~~~~~~~~~~~~

