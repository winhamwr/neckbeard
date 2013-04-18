"""
This module contains optional integrations with common 3rd-party services for
monitoring, alerting, notifications, etc. Right now, it's just a big blob of
things in this file and functions that must be directly included in action
commands. In the future, these will live in a proper contrib module here as
plugins which will be optional loaded based on your configuration. Until the
Plugin/Hook system is built, these things will just exist in their ugly format
and will try to fail gracefully if you don't have them configured.
"""
import httplib
import urllib
import json
import logging
from datetime import datetime, timedelta

import requests
from fabric.api import env, local
from decorator import contextmanager
from requests.exceptions import RequestException

from neckbeard.actions.utils import get_deployer, _get_gen_target

git = None
try:
    import git
except ImportError:
    # Git is only required for certain commands
    pass

try:
    import pynotify
    DT_NOTIFY = True
except ImportError:
    DT_NOTIFY = False

logger = logging.getLogger('actions.contrib_hooks')

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

## Helpers for sending HipChat messages during deployment


@contextmanager
def notifies_hipchat(start_msg, end_msg):
    """
    A decorator to post a notification to hipchat at the start and end of this
    function.

    The `FOO_msg` arguments define template strings that can use the
    following variables as context:

    * `deployer` The deploying user
    * `deployment_name` The deploying environment. Eg. "beta"
    * `generation` The generational target. Eg. "live", "pending"
    * `git_branch` The current git branch name.
    * `duration` The number of wall-clock seconds taken to complete the
      decorated method. Note: Only available to `end_msg`.
    """
    # Ensure we have the required configs
    hipchat_conf = {}
    for key in ['api_token', 'room']:
        hipchat_conf[key] = env.get('hipchat_%s' % key, None)
    for key, value in hipchat_conf.items():
        if value is None:
            logger.warning(
                "No hipchat_%s found. Not notifying.",
                key,
            )
            yield
            logger.warning(
                "No hipchat_%s found. Not notifying.",
                key,
            )
            return
    hipchat_conf['color'] = env.get('hipchat_color', 'green')
    hipchat_conf['from'] = env.get('hipchat_from', 'Neckbeard')

    # Get our git branchname. Fallback to a SHA if detached head
    r = git.Repo('.')
    branch_name = r.commit().hexsha[:7]
    if not r.head.is_detached:
        branch_name = r.active_branch.name

    # Build the message
    context = {
        'deployer': get_deployer(),
        'deployment_name': env.get('_deployment_name', 'unknown'),
        'generation': _get_gen_target().lower(),
        'git_branch': branch_name,
    }
    message = start_msg % context

    _send_hipchat_msg(message, hipchat_conf)

    method_start = datetime.now()
    yield
    duration = datetime.now() - method_start

    context['duration'] = duration.seconds
    message = end_msg % context

    _send_hipchat_msg(message, hipchat_conf)


def _send_hipchat_msg(message, hipchat_conf):
    params = {
        'auth_token': hipchat_conf['api_token'],
        'room_id': hipchat_conf['room'],
        'color': hipchat_conf['color'],
        'from': hipchat_conf['from'],
        'message': message,
    }
    try:
        response = requests.post(
            HIPCHAT_MSG_API_ENDPOINT,
            params=params,
            timeout=5,
        )
    except RequestException, e:
        logger.warning("Failed to post message to hipchat")
        logger.warning("Error: %s", e)
        return

    if response.status_code != requests.codes.ok:
        logger.warning(
            "Bad status code posting message to hipchat: %s",
            response.status_code,
        )
        logger.warning("Response content: %s", response.text)


## Helpers for enforcing git properties on your repository

def _is_tagged_version(repo):
    """
    Check that we are deploying from a tagged commit, and have no uncommitted
    changes.

    Return a boolean.
    """
    # Check that the tag is correct
    head_commit = repo.head.commit
    for tag in reversed(repo.tags):
        if tag.commit == head_commit:
            return True
    return False


def _is_unchanged_from_head(repo):
    # Check that there are no uncommitted changes.
    head_commit = repo.head.commit
    if head_commit.diff(None) != []:  # Diff HEAD commit versus working copy.
        return False
    return True


def _push_tags(repo):
    # Push tags if there is just a single remote.
    if len(repo.remotes) == 1:
        remote = repo.remotes[0]
        logger.info("Pushing tags for current git repository.")
        remote.push(tags=True)
    else:
        logger.warning(
            "Could not push tags, there are %d remotes." % len(repo.remotes))


def _get_git_repo(path='.'):
    if git is None:
        raise ImportError('This check requires GitPython to be installed.')

    try:
        repo = git.Repo(path)
    except git.InvalidGitRepositoryError:
        logger.critical('Not in a git repository.')
        exit(1)
    return repo


## Helper for taking PagerDuty when you deploy

def _take_temporary_pagerduty(
        duration, api_key, user_id, project_subdomain, schedule_key):
    '''
    ``duration`` is the amount of seconds that the pagerduty user associated
    with the ``user_id`` will take over pagerduty at ``project_subdomain`` for
    the schedule associated with the ``schedule_key``. The ``api_key`` is
    needed for authentication and can be found at
    https://``project_subdomain``.pagerduty.com/api_keys.
    '''
    logger.info('Attempting Pagerduty override')

    # Set up headers
    headers = {
        'Content-type': 'application/json',
        'Authorization': 'Token token=%s' % api_key,
    }

    # Set up time start and end dates
    now = datetime.utcnow()
    later = now + timedelta(seconds=duration)
    # Using a trailing Z to indicate UTC time
    payload = {
        'override': {
            'user_id': '%s' % user_id,
            'start': '%sZ' % now.isoformat(),
            'end': '%sZ' % later.isoformat(),
        },
    }

    # Post to pagerduty to override whos on call.
    response = requests.post(
        PAGERDUTY_SCHEDULE_URL % {
            'project_subdomain': project_subdomain,
            'schedule_key': schedule_key,
        },
        data=json.dumps(payload),
        headers=headers,
    )

    # Alert the deployer if there is an error.
    if not response.ok:
        logger.error(
            'Pagerduty override failed status code: "%s".',
            response.status_code,
        )
        logger.error(
            'Error response output: "%s".',
            response.content,
        )
    else:
        logger.info('Pagerduty override has completed successfully.')


## Helpers for announcing deployment for New Relic

def _announce_deployment():
    newrelic_conf = env._deployment_confs['conf'].get('newrelic', {})
    if newrelic_conf.get('announce_deploy', False):
        _send_deployment_end_newrelic()


def _send_deployment_end_newrelic():
    '''
    API: https://rpm.newrelic.com/accounts/87516/applications/402046/deployments/instructions  # noqa
    '''
    GIT_MOST_RECENT_TWO_TAGS = 'git tag | tail -2'
    GIT_MOST_RECENT_COMMIT_MESSAGE = 'git log -1 --format="%s"'
    GIT_CURRENT_TAG = 'git describe --tags'
    GITHUB_COMPARE_OPERATOR = '...'
    NEWRELIC_API_HTTP_METHOD = 'POST'

    def generate_github_changelog_url(tags):
        return GITHUB_COMPARE_URL % GITHUB_COMPARE_OPERATOR.join(tags)

    if env.get('newrelic_api_token', False):
        logger.info('Announcing deployment to newrelic')
        headers = {
            'x-api-key': env.newrelic_api_token,
        }

        # Description is the generation target, e.g. active, pending
        description = '%s ' % (_get_gen_target().lower(),)
        params = {
            'deployment[application_id]': env.newrelic_application_id,
            'deployment[description]': description,
        }
        # Add user information to deployment
        user = get_deployer()
        if user:
            params['deployment[user]'] = user

        # Set the changelog to a github comparison URL
        result = local(GIT_MOST_RECENT_TWO_TAGS, capture=True)
        if result.return_code == 0:
            tags = result.split()
            url = generate_github_changelog_url(tags)
            params['deployment[changelog]'] = url

        # Append the most recent commit message to the description
        result = local(GIT_MOST_RECENT_COMMIT_MESSAGE, capture=True)
        if result.return_code == 0:
            params['deployment[description]'] += result.strip()

        # Set the revision to the current tag
        result = local(GIT_CURRENT_TAG, capture=True)
        if result.return_code == 0:
            params['deployment[revision]'] = result.strip()

        # Attempt to post the deployment to newrelic
        conn = httplib.HTTPSConnection(NEWRELIC_API_HTTP_HOST)
        conn.request(
            NEWRELIC_API_HTTP_METHOD,
            NEWRELIC_API_HTTP_URL,
            urllib.urlencode(params),
            headers,
        )
        response = conn.getresponse()
        if response.status != 201:
            logger.warn('Failed to post deployment to newrelic')


# Helpers for popping Desktop notifications on deployment events

def _send_deployment_done_desktop_notification(pre_deploy_time, deployer):
    if not DT_NOTIFY:
        return
    title = "%(deployment)s %(target)s %(node_name)s deployed"
    content = "Took %(seconds)s seconds"
    time_diff = datetime.now() - pre_deploy_time
    context = {
        'deployment': env._deployment_name,
        'target': _get_gen_target().lower(),
        'node_name': deployer.node_name,
        'seconds': time_diff.seconds,
    }

    notification = pynotify.Notification(title % context, content % context)
    notification.show()
