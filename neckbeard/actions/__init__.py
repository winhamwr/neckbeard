from __future__ import with_statement

from neckbeard.actions.view import view
from neckbeard.actions.up import up
from neckbeard.actions.override import override

__all__ = [view, up, override]

import copy
import httplib
import json
import logging
import os.path
import requests
import time
import urllib
from collections import namedtuple
from datetime import datetime, timedelta
# Using the decorator libs contextmanager because it allows contextmanagers to
# be used as decorators
# See: http://micheles.googlecode.com/hg/decorator/documentation.html#id11
from decorator import contextmanager
from requests.exceptions import RequestException

git = None
try:
    import git
except ImportError:
    # Git is only required for certain commands
    pass

from fabric.api import env, require, prompt, local, task
try:
    import pynotify
    DT_NOTIFY = True
except ImportError:
    DT_NOTIFY = False

from pstat.pstat_deploy import fab_out_opts
from pstat.pstat_deploy.generations import (
    Deployment,
    InfrastructureNode,
)
from pstat.pstat_deploy.deployers.ec2 import Ec2NodeDeployment
from pstat.pstat_deploy.deployers.rds import RdsNodeDeployment

logger = logging.getLogger('status_actions')
time_logger = logging.getLogger('timer')

deploy_timers = {}

fab_output_hides = fab_out_opts[logger.getEffectiveLevel()]
fab_quiet = fab_output_hides + ['stderr']

linked_dirs = ['user_media']

LOG_DIR = '/var/log/pstat'

GITHUB_COMPARE_URL = 'https://github.com/PolicyStat/PolicyStat/compare/%s'
NEWRELIC_API_HTTP_HOST = 'rpm.newrelic.com'
NEWRELIC_API_HTTP_URL = '/deployments.xml'
PAGERDUTY_SCHEDULE_URL = 'https://%(project_subdomain)s.pagerduty.com/api/v1/schedules/%(schedule_key)s/overrides'  # noqa
HIPCHAT_MSG_API_ENDPOINT = "https://api.hipchat.com/v1/rooms/message"

UP_START_MSG = (
    '%(deployer)s <strong>Deploying</strong> '
    '<em>%(deployment_name)s</em> %(generation)s '
    'From: <strong>%(git_branch)s</strong>'
)
UP_END_MSG = (
    '%(deployer)s <strong>Deployed</strong> '
    '<em>%(deployment_name)s</em> %(generation)s '
    "<br />Took: <strong>%(duration)s</strong>s"
)
REPAIR_START_MSG = (
    '%(deployer)s <strong>Repairing</strong> '
    '<em>%(deployment_name)s</em>'
)
REPAIR_END_MSG = (
    '%(deployer)s <strong>Repaired</strong> '
    '<em>%(deployment_name)s</em>'
    "<br />Took: <strong>%(duration)s</strong>s"
)
INCREMENT_START_MSG = (
    '%(deployer)s <strong>Incrementing</strong> '
    '<em>%(deployment_name)s</em>'
)
INCREMENT_END_MSG = (
    '%(deployer)s <strong>Incremented</strong> '
    '<em>%(deployment_name)s</em>'
    "<br />Took: <strong>%(duration)s</strong>s"
)
TERMINATE_START_MSG = (
    '%(deployer)s <strong>Terminating</strong> '
    '<em>%(deployment_name)s</em> %(generation)s'
)
TERMINATE_END_MSG = (
    '%(deployer)s <strong>Terminated</strong> '
    '<em>%(deployment_name)s</em> %(generation)s'
    "<br />Took: <strong>%(duration)s</strong>s"
)





















