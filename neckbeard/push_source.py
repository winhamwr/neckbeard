import os
import time

from fabric.api import sudo, env, put
from fabric.contrib.project import rsync_project

import logging
logger = logging.getLogger('push_source')
logger.setLevel(logging.INFO)

# Large root directories that we want to copy over from version to version
# to save on transfer bandwidth
COPY_DIRS = ('config', 'pstat', 'scripts', 'site_media')

# Paths to exclude when rsyncing project source
EXCLUDES = (
    '/mm/',
    '/failure_ss/',
    '/celeryd*',
    '/config/checker/',
    '/config/jenkins/',
    '/pstat/settings_local.py',
    '/pstat/settings_template.py',
    '/pstat/selenium_tests/',
    '/reports/',
    '/testing/',
    '/user_media/',
    '/docs/.build/',
    '/scripts/reports/server_logs/',
    '*.pyc',
    '*.swp',
    '*.coveragerc',
    '.git/',
    '.gitignore',
    '.gitmodules',
    '.vagrant',
    'coverage.xml',
    'nosetests.xml',
    'pylint.txt',
    'pip-log.txt'
)


def push_source(
    new_source_dir, current_source_dir=None, chown=None, chmod=None):
    """
    Rsync the current project to `new_source_dir`, optionally first copying the
    contents of `current_source_dir` to provide faster rsync and optionally
    performing a chown on the resulting directory with the `chown`
    `user:group`.

    `chmod` can be either an octal representation of chmod integers, or a
    string of the "u+rw,g-rw,o-r" variety.
    """
    logger.info(u"Rsyncing the src to %s", env.host_string)

    # Copy the current source to our new source directory (preserving file
    # attributes) so that we can use rsync to push only the changed files
    sudo("mkdir --parents %s" % new_source_dir)

    if current_source_dir:
        logger.info(
            "Copying existing source as a base from: %s",
            current_source_dir,
        )
        for copy_dir in COPY_DIRS:
            from_dir = os.path.join(current_source_dir, copy_dir)
            to_dir = os.path.join(new_source_dir, copy_dir)
            sudo("cp -r --dereference --preserve %s %s" % (from_dir, to_dir))

        # Remove copied .pyc files and empty directories
        sudo('find %s -name "*.pyc" -delete' % current_source_dir)
        sudo('find %s -type d -empty -delete' % current_source_dir)

    # Give the rsync user permissions to change file attributes
    logger.info("Giving current user permission to modify files")
    sudo("chown -R %s %s" % (env.user, new_source_dir))

    # Rsync the source to the new directory
    logger.info(u"Rsync beginning")
    start = time.time()

    def do_rsync():
        # rsync_project already uses the rsync options:
        # http://docs.fabfile.org/en/1.4.0/api/contrib/project.html#fabric.contrib.project.rsync_project  # noqa
        # --perms
        # --times
        # --human-readable
        # --recursive
        # --verbose
        # --compress
        extra_opts = [
            '--links',
            '--no-perms',
            '--executability',
            '--no-verbose',
            '--stats',
            '''--rsh="ssh -o 'StrictHostKeyChecking no'"''',
        ]
        return rsync_project(
            '%s' % new_source_dir,
            local_dir='../.',
            exclude=EXCLUDES,
            delete=True,
            extra_opts=' '.join(extra_opts),
        )
    output = do_rsync()
    if output.failed:
        logger.warning(
            "Rsync exited with code: %s. Retrying" % output.return_code
        )
        start = time.time()
        output = do_rsync()
        if output.failed:
            logger.critical("Rsync failed again. Aborting.")
            exit(1)

    logger.info("Rsync complete. Took %s seconds", time.time() - start)
    logger.info("Rsync stats: %s", output)

    if chown:
        sudo("chown -R %s %s" % (chown, new_source_dir))
    if chmod is not None:
        if type(chmod) == int:
            # This is an octal permission mask. Convert it to a string
            # representation.
            chmod = "%o" % chmod
        sudo("chmod -R %s %s" % (chmod, new_source_dir))


def push_ssl_crt():
    """
    Push the wildcard ssl cert and the godaddy cert bundle to the remote host.
    """
    logger.info(u"Pushing SSl Certificates")
    key = '%(config_folder)s/%(ssl_key)s' % env
    crt = '%(config_folder)s/%(ssl_crt)s' % env
    bundle = '%(config_folder)s/rapidssl_ca_bundle.pem' % env
    logger.info(u"Using SSL keys and certs at %s and %s" % (key, crt))

    # Putting to /tmp and moving for permission purposes
    put(key, '/tmp/_.policystat.com.key')
    sudo('mv /tmp/_.policystat.com.key /etc/ssl/private/_.policystat.com.key')
    sudo('chmod 640 /etc/ssl/private/_.policystat.com.key')
    sudo('chown root:ssl-cert /etc/ssl/private/_.policystat.com.key')

    put(crt, '/tmp/_.policystat.com.crt')
    put(bundle, '/tmp/rapidssl_ca_bundle.pem')
    # Combine the crt with the rapidssl intermediate bundle
    sudo('cat /tmp/_.policystat.com.crt /tmp/rapidssl_ca_bundle.pem > \
    /tmp/_.policystat.com.crt.bundled')
    sudo(
        'mv /tmp/_.policystat.com.crt.bundled '
        '/etc/ssl/certs/_.policystat.com.crt'
    )
    sudo('chmod 777 /etc/ssl/certs/_.policystat.com.crt')


def sudo_bg(cmd, **kwargs):
    """
    Run a sudo command, but don't wait for the command to finish.
    """
    cmd_tpl = (
        "nohup sh -c '%s' "
        ">& /dev/null < /dev/null &"
    )

    return sudo(cmd_tpl % cmd, pty=False, **kwargs)
