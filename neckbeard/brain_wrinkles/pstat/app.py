"""
Deployment provisioning (service-agnostic) for a PolicyStat app server.
"""
import logging
import time
import os

from fabric.api import sudo, run, env, require, hide, cd, put
from fabric.contrib.files import upload_template
from fabric.contrib.project import rsync_project

from neckbeard.environment_manager import WAIT_TIME
from neckbeard.brain_wrinkles import BaseProvisioner
from neckbeard.brain_wrinkles.pstat import (
    upload_template_changed,
    put_changed,
)
from neckbeard.output import fab_out_opts, fab_quiet_opts

logger = logging.getLogger('prov:pstat:app')

fab_output_hides = fab_out_opts[logger.getEffectiveLevel()]
fab_quiet = fab_quiet_opts[logger.getEffectiveLevel()]

LINKED_DIRS = ['user_media']
LOG_DIR = '/var/log/pstat'
VENV_PTH = '/home/policystat/env'
PYTHON_BIN = '%s/bin/python' % VENV_PTH
PIP_BIN = '%s/bin/pip' % VENV_PTH
MEDIA_STORAGE_ROOT = '/mnt/pstat_storage'  # Storage for user_media files
GITHUB_TERRARIUM = 'git://github.com/PolicyStat/terrarium.git@v1.0.0rc2#egg=terrarium'  # noqa
ACTIVE_SOURCE_SYMLINK = '/opt/pstat/versions/current'
CONFIG_TPL_DIR = os.path.abspath('../config/tpl')
EC2_SCRIPTS_TPL_DIR = os.path.abspath('../config/ec2_scripts/tpl')
SUPERVISORD = 'supervisord'
API_ENDPOINT = 'https://%(private_dns)s/api/v1/'

FILE_OWNER = 'policystat'
F_CHOWN = '%s:%s' % (FILE_OWNER, FILE_OWNER)


class AppServerProvisioner(BaseProvisioner):
    """
    Provisioner for updating the ubuntu app server with new policystat
    application code.
    """
    services = ['supervisor']
    # Packages this server doesn't need
    vestigial_packages = []

    def __init__(self, *args, **kwargs):
        super(AppServerProvisioner, self).__init__(*args, **kwargs)

        # Services that have been modified. This is useful if there are
        # multiple ways to modify a service, but you only want to possibly
        # restart that service one time without requiring specific coordination
        self.modified_services = []

    def start_services(self):
        """
        Start services that should be stopped during initial provisioning.
        """
        logger.info("Starting services: %s", self.services)
        for service in self.services:
            with hide(*fab_quiet):
                sudo('service %s start' % service)

    def stop_services(self):
        """
        Stop the services started by ``self.start_services``.
        """
        logger.info("Stopping services: %s", self.services)
        for service in self.services:
            with hide(*fab_quiet):
                sudo('service %s stop' % service)

    def fix_folder_perms(self):
        """
        Fix folder permissions that can break while restoring.
        """
        logger.info("Fixing EBS volume folder permissions")
        if self.is_local_db():
            with hide(*fab_quiet):
                sudo('chown -R mysql:mysql /var/lib/mysql')
                sudo('chown -R mysql:adm /var/log/mysql')

        with hide(*fab_quiet):
            sudo('chown -R %s /var/log/uwsgi' % F_CHOWN)
            sudo('chown -R %s /var/log/celery' % F_CHOWN)
            sudo('chown -R %s /var/log/pstat' % F_CHOWN)

            # Ensure the pstat log dir is writable by root
            sudo('chmod -R g+w /var/log/pstat')

            # One-off fix for wrong permissions on /etc/cron.d/calabard_monitor
            sudo('chown root:root /etc/cron.d/calabard_monitor')

            # Ensure the media storage directory exists
            sudo('mkdir %s --parents' % MEDIA_STORAGE_ROOT)
            sudo('chown -R %s %s' % (F_CHOWN, MEDIA_STORAGE_ROOT))
            sudo('chmod -R u+rw,g+rw,o+r,o-w %s' % MEDIA_STORAGE_ROOT)

    def do_first_launch_config(self):
        self._do_set_hostname()

        if self.is_local_db():
            # Install mysql locally
            mysql_install = 'DEBIAN_FRONTEND=noninteractive apt-get \
            -o Dpkg::Options::="--force-confnew" -y --force-yes -qq \
            install mysql-server-5.1'
            sudo(mysql_install)

        logger.info("Removing vestigial packages: %s", self.vestigial_packages)

        for package in self.vestigial_packages:
            with hide(*fab_output_hides):
                result = sudo('apt-get remove %s --yes --force-yes' % package)
            if result.failed:
                logger.warning("Failed to remove package: %s", package)
                logger.warning("Error: %s", result)

        with hide(*fab_output_hides):
            push_ssl_crt()

        self._fix_pstat_logging_perms()
        self._create_db_and_user()
        self._configure_sphinx()

        # Install terrarium
        logger.info("Installing Terrarium")
        with hide(*fab_quiet):
            run(
                'source %s/bin/activate && %s install -e %s'
                ' ' % (VENV_PTH, PIP_BIN, GITHUB_TERRARIUM)
            )
        # Install boto for terrarium source sync
        logger.info("Installing Boto for terrarium s3 usage")
        with hide(*fab_quiet):
            run(
                'source %s/bin/activate && %s install boto'
                ' ' % (VENV_PTH, PIP_BIN)
            )

        if env.get('is_newrelic_monitored', False):
            self._configure_newrelic()

    def _replace_text_in_files(self, paths, search, replace):
        sudo("sed -i 's/%s/%s/' %s" % (search, replace, ' '.join(paths)))

    def _do_set_hostname(self):
        logger.info("Configuring hostname and /etc/hosts")

        hostname = env.hostname
        logger.info('Setting hostname to %s', hostname)
        # 127.0.0.1 localhost HOSTNAME
        # edit the /etc/hosts file first, otherwise
        # sudo may complain about the hostname not being resolvable
        with hide(*fab_output_hides):
            self._append_text_to_line_in_files(
                ['/etc/hosts'],
                '^127.0.0.1',
                ' %s' % hostname,
            )
            sudo('hostname %s' % hostname)
            # Save the hostname so it is restored on reboot
            sudo('hostname > /etc/hostname')

    def do_update(self, node_role_map, node_roles, first_run=False):
        """
        Assumes all of the packages and system-level requirements have already
        been installed and configured.
        """
        require('use_rds')
        require('pstat_instance')
        require('pstat_url')
        require('project_root')
        require('config_folder')
        require('ssl_prefix')
        require('backup')
        require('aws_access_key_id')
        require('aws_secret_access_key')
        require('sphinx_counter')
        require('key_filename')
        require('calabar_conf_context')
        require('loggly_inputs')
        require('sphinx_counter')
        require('ipsec_confs')
        require('hostname')
        require('enable_periodic_tasks')

        logger.info("Starting to provision %s", env.host_string)

        for ipsec_name, _ in env.ipsec_confs.items():
            # Require all of the pre-shared key configs
            require('ipsec_psk_%s' % ipsec_name)

        if first_run:
            self.do_first_launch_config()

        self._stop_celery()

        self._update_cache_settings(node_role_map['memcached']['all'])
        self._update_sphinx_settings(
            node_role_map['celery_backend']['same_az'],
            node_roles,
        )
        self._update_celery_backend_settings(
            node_role_map['sphinx_search_indexer']['same_az'],
        )
        ldap_api_nodes = node_role_map['has_ldap_access']
        self._update_ldap_api_endpoint_settings(
            all_ldap_api_nodes=ldap_api_nodes['all'],
            same_az_ldap_api_nodes=ldap_api_nodes['same_az'],
            node_roles=node_roles,
        )
        self._update_celery_ldap_settings(node_roles)

        # Package and push the app to the new instance
        env.project_root_src = '/opt/pstat/versions/%(timestamp)s' % env
        source_dir = env.project_root_src
        current_source_dir = None
        if not first_run:
            current_source_dir = env.project_root
        with hide(*fab_output_hides):
            push_source(
                new_source_dir=source_dir,
                current_source_dir=current_source_dir,
                chown=F_CHOWN,
                chmod="u+rw,g+rw,o-rw",
            )
        self._make_media_readable(source_dir)
        self._configure_settings_local(
            source_dir,
            env.pstat_settings,
            chown=F_CHOWN,
        )
        self._configure_settings_target(
            source_dir,
            env.settings_target,
            chown=F_CHOWN,
        )
        self.configure_terrarium(source_dir=source_dir, user=FILE_OWNER)
        self._activate_new_source(
            source_dir,
            [ACTIVE_SOURCE_SYMLINK, env.project_root],
        )
        self._run_db_migrations(user=FILE_OWNER)

        # Link up the attachments and upload directories from /mnt/
        self._link_storage_dirs()

        self._configure_webservers(node_roles)
        building_search_index = self._build_search_index()

        self._create_media_folder()
        self._collect_static_media()

        self._create_500_page()
        self._restart_webservers()

        # Services managed via supervisord
        self._configure_celery(node_roles)
        self._update_supervisord()
        self._configure_calabar()
        self._configure_ipsec()
        self._start_celery()

        self._configure_loggly()
        self._configure_pstat_cron_jobs()
        self._configure_email_sending()

        if first_run:
            self._sync_s3_media()

        if building_search_index:
            self._wait_for_search_indexing()
        self._ensure_sphinx_running()
        self._configure_sphinx_cron()

        logger.info("Provisioner completed successfully")

    def _activate_new_source(self, source_dir, active_version_symlinks):
        """
        Create a symlink at each of `active_version_symlinks`
        towards the actual `source_dir`.

        The `source_dir` will probably be in a timestamped directory like
        `/opt/pstat/versions/<timestamp>`.

        Example symlinks:

            [`/opt/pstat/versions/current`, `/var/www/pstatbeta.com`]
        """
        # Switch the symlink and use our new project
        logger.info("Activating new source via symlinks")
        for symlink in active_version_symlinks:
            logger.info("Symlinking %s", symlink)
            symlink_dir, _ = os.path.split(symlink)
            with hide(*fab_output_hides):
                sudo('mkdir -p %s' % symlink_dir)
                sudo('rm -f %s' % symlink)
                sudo('ln -s %s %s' % (source_dir, symlink))

        # Clean out any stale pycs that may have been generated by queued
        # up processes that were using the old symlink
        with hide(*fab_output_hides):
            sudo('find %s -name "*.pyc" -delete' % source_dir)

    def configure_terrarium(self, source_dir, user):
        require('project_root')
        require('dev_aws_access_key')
        require('dev_aws_secret_key')
        require('dev_requirements_bucket')
        logger.info("Creating pstat virtualenv with terrarium")

        # Ensure the required user owns the virtualenv's parent dir so that
        # they can create backups during the terrarium build
        venv_parent_dir, _ = os.path.split(VENV_PTH)
        with hide(*fab_output_hides):
            sudo('chown -R %s %s' % (user, venv_parent_dir))

        # Delete any terrarium-backed-up environment to avoid permission
        # annoyances
        with hide(*fab_output_hides):
            sudo('rm -rf %s.bak' % VENV_PTH)

        # Now actually create the new virtualenv with terrarium
        pstat = '%s/config/ec2_scripts/tpl/pstat' % source_dir
        args = {
            'python': PYTHON_BIN,
            'terrarium': '%s/bin/terrarium' % VENV_PTH,
            'virtualenv': VENV_PTH,
            'requirements': ' '.join([
                '%s/%s' % (pstat, req)
                for req in [
                    'requirements.txt',
                    'dev_requirements.txt',
                    'src_requirements.txt',
                    'sys_requirements.txt',
                ]
            ]),
        }
        args.update(env)
        with hide(*fab_output_hides):
            result = sudo(
                '%(python)s '
                '%(terrarium)s '
                '--target %(virtualenv)s '
                '--s3-bucket "%(dev_requirements_bucket)s" '
                '--s3-access-key %(dev_aws_access_key)s '
                '--s3-secret-key %(dev_aws_secret_key)s '
                'install '
                '%(requirements)s'
                ' ' % args,
                user=user,
            )

        if result.failed:
            logger.critical(
                'Failed to make a virtual environment. Exit code %s',
                result.return_code,
            )
            logger.critical('Result output: %s', result)
            exit(result.return_code)
        # Create symlink to policystat path file
        pstat_pth = (
            'ln -sf %s/config/ec2_scripts/tpl/pstat/pstat.pth'
            ' ' % source_dir
        )
        pstat_pth_link = '%s/lib/python2.6/site-packages/pstat.pth' % VENV_PTH
        with hide(*fab_output_hides):
            sudo('%s %s' % (pstat_pth, pstat_pth_link), user=user)

            sudo('chmod -R g+rwx %s' % VENV_PTH)

    def is_local_db(self):
        if env.db_host == 'localhost':
            return True

        return False

    def _sync_s3_media(self):
        """
        Sync S3 media between two buckets. Used to keep beta/training files in
        sync with live.
        """
        # Copy media from one S3 bucket to another if needed
        logger.info("Syncing S3 Media")
        if env.get('bucket_copy', False):
            with cd(env.project_root):
                cmd = [
                    '%s scripts/s3_copy_bucket.py' % PYTHON_BIN,
                    env.bucket_copy['from_aws_access_key'],
                    env.bucket_copy['from_aws_secret_key'],
                    env.bucket_copy['from_aws_storage_bucket'],
                    env.bucket_copy['to_aws_access_key'],
                    env.bucket_copy['to_aws_secret_key'],
                    env.bucket_copy['to_aws_storage_bucket'],
                    env.bucket_copy['to_aws_user_email'],
                    '&',
                ]
                logger.info(u"Copying S3 media")
                with hide(*fab_output_hides):
                    run('%s < /dev/null' % " ".join(cmd))

    def _append_text_to_line_in_files(
            self, path, line_matching, text_to_append):
        sudo(
            'sed -i "/%s/s|$|%s|" %s' % (
                line_matching, text_to_append, ' '.join(path)
            )
        )

    def _configure_newrelic(self):
        logger.info(u"Enabling the newrelic server monitoring agent")
        # Activate the server monitoring agent
        with hide(*fab_output_hides):
            sudo('sudo update-rc.d newrelic-sysmond enable')
            sudo('/etc/init.d/newrelic-sysmond start')

    def _create_500_page(self):
        # Build the static 500 page
        logger.info(u"Creating static 500 error page")
        with cd('%(project_root)s/pstat' % env):
            with hide(*fab_output_hides):
                sudo(
                    '%s manage.py make_static_500' % PYTHON_BIN,
                    user='policystat')

    def _restart_webservers(self):
        logger.info("Restarting Web Servers")
        with hide(*fab_output_hides):
            sudo('touch /etc/uwsgi/policystat.yaml')
            sudo_bg('service nginx restart')
        self._ensure_uwsgi_up()

    def _create_media_folder(self):
        logger.info(u"Creating user_media/merged")
        # Make sure we have a media merging folder
        with hide(*fab_output_hides):
            merged_dir = '%s/user_media/merged' % env.project_root_src
            sudo('mkdir --parents %s' % merged_dir)
            sudo('chown %s %s' % (F_CHOWN, merged_dir))

    def _collect_static_media(self):
        logger.info(u"Collecting static media")
        with hide(*fab_output_hides):
            with cd('%(project_root)s/pstat' % env):
                collect = "%s manage.py collectstatic -v0 --noinput"
                sudo(collect % PYTHON_BIN, user='policystat')
                sudo('chown %s %s/static' % (F_CHOWN, env.project_root))

    def _configure_webservers(self, node_roles):
        """
        Configure nginx and uwsgi.
        """
        logger.info("Configuring uwsgi")
        with hide(*fab_quiet):
            # Configure the uwsgi app
            context = {
                'project_root': env.project_root,
                'domain': env.pstat_url,
            }
            upload_template(
                '../config/tpl/newrelic/policystat.ini',
                '/etc/newrelic/policystat.ini',
                context,
                use_sudo=True
            )
            upload_template(
                '../config/tpl/uwsgi/policystat.yaml',
                '/etc/uwsgi/policystat.yaml',
                context,
                use_sudo=True
            )

            # Configure the supervisord config for uwsgi
            newrelic_conf = self.conf.get('newrelic', {})
            new_relic_environment = newrelic_conf.get('environment', None)
            context = {
                'new_relic_environment': new_relic_environment,
            }
            changed = upload_template_changed(
                '../config/tpl/uwsgi/etc/supervisor/conf.d/uwsgi.conf',
                '/etc/supervisor/conf.d/uwsgi.conf',
                use_sudo=True,
                mode=0600,
                use_jinja=True,
                context=context,
            )
            if changed:
                self.modified_services.append(SUPERVISORD)

            # Give user policystat access to configuration files
            files = [
                '/etc/uwsgi/policystat.yaml',
                '/etc/newrelic/policystat.ini',
            ]
            sudo('chown %s %s' % (F_CHOWN, ' '.join(files)))

            logger.info("Configuring nginx")
            # Configure the nginx host
            context = {
                'project_root': env.project_root,
                'domain': env.pstat_url,
            }
            upload_template(
                '../config/tpl/nginx/pstat',
                '/etc/nginx/sites-available/%s' % env.pstat_url,
                context,
                use_sudo=True,
            )

            # Make sure no other sites are enabled
            sudo('rm -f /etc/nginx/sites-enabled/*')

            # Enable our site
            sudo(
                'ln -s '
                '/etc/nginx/sites-available/%(pstat_url)s '
                '/etc/nginx/sites-enabled/%(pstat_url)s' % env
            )

    def _make_media_readable(self, source_dir):
        """
        Ensure that Nginx etc can read the `site_media`.
        """
        logger.info("Making site_media readable")

        site_media = os.path.join(source_dir, 'site_media')
        with hide(*fab_output_hides):
            sudo('chmod -R o+r %s' % site_media)

    def _configure_settings_local(self, source_dir, settings_dict, chown=None):
        require('db_host')
        require('db_user')
        require('db_password')
        require('db_name')
        require('enable_periodic_tasks')
        logger.info("Configuring settings_local.py")

        settings_dict['database_name'] = env.db_name
        settings_dict['database_user'] = env.db_user
        settings_dict['database_host'] = env.db_host
        settings_dict['database_password'] = env.db_password
        settings_dict['enable_periodic_tasks'] = env.enable_periodic_tasks

        target = '%s/pstat/settings_local.py' % source_dir
        with hide(*fab_output_hides):
            upload_template(
                'pstat/settings_local.py',
                target,
                context=settings_dict,
                use_jinja=True,
                use_sudo=True,
                template_dir=CONFIG_TPL_DIR,
            )
            if chown:
                sudo('chown %s %s' % (chown, target))

    def _configure_settings_target(
        self, source_dir, settings_target, chown=None,
    ):
        logger.info("Configuring settings_target.py")

        target = '%s/pstat/settings_target.py' % source_dir
        with hide(*fab_output_hides):
            upload_template(
                'pstat/settings_target.py',
                target,
                context={'settings_target': settings_target},
                use_jinja=True,
                use_sudo=True,
                template_dir=CONFIG_TPL_DIR,
            )
            if chown:
                sudo('chown %s %s' % (chown, target))

    def _run_db_migrations(self, user):
        # Now run migrations
        logger.info("Running DB migrations")
        with cd('%(project_root)s/pstat' % env):
            result = sudo(
                '%s manage.py syncdb --noinput --migrate' % PYTHON_BIN,
                user=user)

        if result.failed:
            logger.critical(result)
            logger.critical("Migration failed")
            exit(1)

    def _create_db_and_user(self):
        require('db_host')
        require('db_user')
        require('db_password')
        require('db_name')
        require('db_master_user')
        require('db_master_password')
        logger.info("Creating the database and DB user")

        context = {
            'db_user': env.db_user,
            'password': env.db_password,
            'db_name': env.db_name,
        }
        with hide(*fab_output_hides):
            upload_template(
                'pstat/create_db.sql',
                '/tmp/create_db.sql',
                mode=0700,
                context=context,
                use_jinja=True,
                template_dir=CONFIG_TPL_DIR,
            )

        start_mysql_tpl = (
            "mysql --user=%s --password=%s --host=%s --batch --force"
        )
        start_mysql_args = (
            env.db_master_user,
            env.db_master_password,
            env.db_host,
        )
        start_mysql = start_mysql_tpl % start_mysql_args

        with hide(*fab_quiet):
            run("%s < %s" % (start_mysql, '/tmp/create_db.sql'), shell=True)

    def _configure_sphinx(self):
        """
        Build the appropriate `/etc/sphinx.conf` file and create the sphinx
        indexer script.
        """
        require('db_host')
        require('db_user')
        require('db_password')
        require('db_name')
        require('sphinx_counter')
        logger.info("Configure sphinx search daemon")

        # Build /etc/sphinx.conf
        context = {
            'database_user': env.db_user,
            'database_password': env.db_password,
            'database_name': env.db_name,
            'database_host': env.db_host,
            'counter': env.sphinx_counter,
        }
        with hide(*fab_output_hides):
            logger.info("Building /etc/sphinxsearch/sphinx.conf")
            upload_template(
                'sphinx/sphinx.conf',
                '/etc/sphinxsearch/sphinx.conf',
                context=context,
                use_jinja=True,
                template_dir=CONFIG_TPL_DIR,
                use_sudo=True,
                mode=0644,
            )

        script_destination = (
            '/var/lib/sphinxsearch/%s_indexer.sh' % env.db_name
        )
        with hide(*fab_output_hides):
            logger.info("Building %s", script_destination)
            put(
                '../config/tpl/sphinx/policystat_indexer.sh',
                script_destination,
                mode=0755,
                use_sudo=True,
            )
            sudo('chown %s %s' % (F_CHOWN, script_destination))

    def _update_sphinx_settings(self, sphinx_nodes, node_roles):
        logger.info("Updating SPHINX_SERVER setting")
        assert len(sphinx_nodes) == 1
        node = sphinx_nodes[0]
        env.pstat_settings['SPHINX_SERVER'] = node.boto_instance.private_dns_name  # noqa

        env.pstat_settings['SPHINX_STATUS_CHECK_INDEX'] = False
        if 'sphinx_search_indexer' in node_roles:
            # If this node is a search indexer, we should enable the index time
            # status check
            env.pstat_settings['SPHINX_STATUS_CHECK_INDEX'] = True

    def _update_celery_backend_settings(self, celery_backend_nodes):
        logger.info("Updating CELERY_BACKEND_HOST setting")
        assert len(celery_backend_nodes) == 1
        node = celery_backend_nodes[0]
        env.pstat_settings['CELERY_BACKEND_HOST'] = node.boto_instance.private_dns_name  # noqa

    def _update_ldap_api_endpoint_settings(
        self, all_ldap_api_nodes, same_az_ldap_api_nodes, node_roles,
    ):

        env.pstat_settings['DYNAMIC_LDAP_API_ENDPOINTS'] = []

        if 'has_ldap_access' in node_roles:
            logger.info("Node is an LDAP API endpoint")
            # LDAP API endpoint nodes don't need to use themselves
            return
        logger.info("Configuring LDAP API endpoint usage")

        same_az_first = BaseProvisioner.order_nodes_by_same_az(
            all_ldap_api_nodes,
            same_az_ldap_api_nodes,
        )
        for node in same_az_first:
            api_endpoint = API_ENDPOINT % {
                'private_dns': node.boto_instance.private_dns_name,
            }
            env.pstat_settings['DYNAMIC_LDAP_API_ENDPOINTS'].append(
                api_endpoint,
            )

    def _update_celery_ldap_settings(self, node_roles):
        """
        Should this node run `celery_ldap`?
        """
        env.pstat_settings['enable_celery_ldap'] = False
        env.enable_celery_ldap = False
        if 'has_ldap_access' in node_roles:
            logger.info("Configuring node to run celery_ldap")
            env.pstat_settings['enable_celery_ldap'] = True
            env.enable_celery_ldap = True
            return

        logger.info("Node not configured to run celery_ldap")

    def _update_cache_settings(self, memcached_nodes):
        """
        Update the pstat_settings['CACHE_BACKEND'] environment variable with
        all running active app servers.
        """
        logger.info("Updating CACHE_BACKEND settings")
        assert len(memcached_nodes) > 0
        if memcached_nodes:
            memcached_port = 11211
            cache_str = 'memcached://'
            cache_instances = []
            for node in memcached_nodes:
                cache_instances.append(
                    "%s:%s" % (
                        node.boto_instance.private_dns_name,
                        memcached_port,
                    )
                )
            cache_str += ';'.join(cache_instances)
            env.pstat_settings['CACHE_BACKEND'] = cache_str

    def _link_storage_dirs(self):
        """
        Create (if they don't exist) and link the attachments and upload dirs
        from /vol/
        """
        logger.info("Linking user_media storage directory")
        dirs = [
            (name, '%(project_root_src)s/' % env + name)
            for name in LINKED_DIRS
        ]

        for name, link_name in dirs:
            with hide(*fab_output_hides):
                storage_dir = os.path.join(MEDIA_STORAGE_ROOT, name)
                sudo('mkdir %s --parents' % storage_dir)
                sudo('chown %s %s' % (F_CHOWN, storage_dir))
                sudo('chmod u+rw,g+rw,o+r,o-w %s' % storage_dir)

                sudo('ln -s %s %s' % (storage_dir, link_name))

    def _build_search_index(self):
        """
        Start building the full search index.

        Returns true if index building was required.
        """
        logger.info("Checking if full sphinx index build required")
        check_files = [
            '/var/lib/sphinxsearch/data/document.spp',
        ]
        needs_init = False
        for check_f in check_files:
            with hide(*fab_quiet):
                check_result = sudo('ls %s' % check_f)
            if check_result.failed:
                needs_init = True
                break

        if not needs_init:
            logger.info("Sphinx indexes already exist")
            return False

        logger.info("Building full sphinxsearch index")
        with hide(*fab_output_hides):
            # Chown relevant directories to belong to policystat.
            sudo(
                'chown -R %s '
                '/var/lib/sphinxsearch /var/log/sphinxsearch'
                '' % F_CHOWN
            )

            with hide(*fab_quiet):
                # Stop searchd
                sudo('stop sphinxsearch')
                sudo('killall searchd')

            # Build the main index then the delta
            index_result = sudo_bg(
                'indexer document && indexer document_delta',
                user='policystat',
            )
            if index_result.failed:
                logger.critical(
                    "Error building sphinx indexes. Result: %s",
                    index_result,
                )

        return True

    def _wait_for_search_indexing(self):
        logger.info("Waiting for initial sphinx indexing to complete")

        indexer_exists = True
        while indexer_exists:
            with hide(*fab_quiet):
                indexer_found = run('pgrep indexer')
            indexer_exists = indexer_found.succeeded
            if indexer_exists:
                logger.info(
                    "Waiting %s s for the sphinx indexer to finish. PID %s",
                    WAIT_TIME,
                    indexer_found,
                )
                time.sleep(WAIT_TIME)

        logger.info("Sphinx indexing complete")

    def _ensure_sphinx_running(self):
        """
        Ensure the sphinx search daemon is running and index are built. It can
        crash if it's restarted during an index rotation (which happens via
        cron).
        """
        logger.info("Ensuring sphinx is running")

        def _is_running():
            check_cmd = "pgrep searchd > /dev/null"
            with hide(*fab_quiet):
                check_result = sudo(check_cmd)

            return check_result.return_code == 0

        def _start_sphinx(stop_first=False):
            start_cmd = "start sphinxsearch"

            with hide(*fab_output_hides):
                if stop_first:
                    with hide(*fab_quiet):
                        sudo("stop sphinxsearch")
                sudo(start_cmd)

        wait_str = (
            "searchd not running. "
            "Restarting and waiting %(wait_seconds)s"
        )
        _start_sphinx(stop_first=True)
        self.wait_for_condition(
            _is_running,
            wait_str,
            retry_action=_start_sphinx,
            wait_seconds=WAIT_TIME,
            prompt_cycles=2,
        )

    def _configure_sphinx_cron(self):
        """
        Configure the sphinx search daemon and indexing.
        """
        logger.info("Configuring sphinx index-building cronjobs")

        # Ensure that the cron jobs for re-indexing are configured
        script_path = '/var/lib/sphinxsearch/policystat_indexer.sh'
        cron_location = '/etc/cron.d/policystat_sphinx'

        context = {
            'indexer_script': script_path,
            'log_dir': '/var/log/pstat',
        }
        with hide(*fab_output_hides):
            upload_template(
                "../config/tpl/sphinx/cron.d/policystat_sphinx",
                cron_location,
                context,
                use_sudo=True)
            sudo('chown root:root %s' % cron_location)

    def _needs_syslog_ng_restart(self):
        # If it's not currently running, it needs a restart
        with hide(*fab_quiet):
            with hide('warnings'):
                result = sudo('/etc/init.d/syslog-ng status')
            if result.failed:
                logger.info("syslog-ng not running")
                return True

            with hide('warnings'):
                changed_conf = sudo(
                    (
                        'cmp -s /etc/syslog-ng/syslog-ng.conf '
                        '/etc/syslog-ng/syslog-ng.conf.bak'
                    ),
                    shell=True,
                )
        if changed_conf.return_code != 0:
            logger.info("syslog-ng config changed")
            return True

        return False

    def _configure_loggly(self):
        # Temporary check to install syslog-ng until the AMI is updated
        logger.info("Configuring Loggly")
        with hide(*fab_output_hides):
            install_check = run('which syslog-ng', shell=True)
            if install_check.return_code != 0:
                # syslog-ng isn't installed
                sudo('apt-get -y --force-yes install syslog-ng')

            # Update the config
            context = env.loggly_inputs
            upload_template(
                '../config/tpl/syslog_ng/syslog-ng.conf',
                '/etc/syslog-ng/syslog-ng.conf',
                context,
                use_sudo=True)

            if self._needs_syslog_ng_restart():
                logger.info("Restarting syslog-ng")
                with hide(*fab_output_hides):
                    result = sudo('/etc/init.d/syslog-ng restart')
                    if result.failed:
                        logger.critical("Failed to restart syslog-ng")
                        logger.critical(result)
                        exit(1)

    def _configure_calabar(self):
        logger.info("Configuring Calabar")
        tunnel_confs_dir = '../config/tpl/calabar/tunnel_confs/'
        configuration_changed = False
        # Push the main calabar.conf file
        with hide(*fab_output_hides):
            changed = put_changed(
                '../config/tpl/calabar/calabar.conf',
                '/etc/calabar/calabar.conf',
                use_sudo=True,
                mode=0600)
            if changed:
                configuration_changed = True

        # Push each of the tunnel configs
        # Need to make sure the tunnel_confs directory exists
        with hide(*fab_output_hides):
            sudo('mkdir --parents /etc/calabar/tunnel_confs')

        with hide(*fab_output_hides):
            for dirpath, _, filenames in os.walk(tunnel_confs_dir):
                for filename in filenames:
                    calabar_config_file = os.path.join(dirpath, filename)
                    changed = upload_template_changed(
                        calabar_config_file,
                        '/etc/calabar/tunnel_confs/',
                        context=env.calabar_conf_context,
                        use_sudo=True,
                        mode=0600)
                    if changed:
                        configuration_changed = True

        if configuration_changed:
            logger.info("Calabar config changed. Restarting calabard.")
            with hide(*fab_output_hides):
                sudo('supervisorctl stop calabard')
                sudo('supervisorctl start calabard')

    def _stop_celery(self):
        logger.info("Stopping Celery Service")
        with hide(*fab_output_hides):
            sudo_bg('supervisorctl stop celery:')

    def _start_celery(self):
        logger.info("Starting Celery Service")
        with hide(*fab_output_hides):
            sudo_bg('supervisorctl start celery:')

    def _ensure_uwsgi_up(self):
        logger.info("Ensuring uwsgi is running")
        with hide(*fab_quiet):
            sudo_bg('supervisorctl start uwsgi')

    def _configure_celery(self, node_roles):
        logger.info("Updating Celery's supervisord config")
        hostname = env.hostname
        enable_periodic_tasks = env.enable_periodic_tasks
        enable_celery_ldap = env.enable_celery_ldap

        celery_conf = self.conf.get('celery', {})
        newrelic_conf = self.conf.get('newrelic', {})
        new_relic_environment = newrelic_conf.get('environment', None)
        context = {
            'new_relic_environment': new_relic_environment,
            'hostname': hostname,
            'enable_periodic_tasks': enable_periodic_tasks,
            'enable_celery_ldap': enable_celery_ldap,
            'celery': celery_conf,
        }
        with hide(*fab_output_hides):
            changed = upload_template_changed(
                '../config/tpl/celery/etc/supervisor/conf.d/celeryd.conf',
                '/etc/supervisor/conf.d/celeryd.conf',
                use_sudo=True,
                mode=0600,
                use_jinja=True,
                context=context,
            )
        if changed:
            self.modified_services.append(SUPERVISORD)

    def _update_supervisord(self):
        if SUPERVISORD not in self.modified_services:
            logger.info("No supervisord reload required.")
            return

        logger.info("supervisord configs changed. Reloading.")
        with hide(*fab_quiet):
            sudo_bg('supervisorctl update')

    def _configure_ipsec(self):
        logger.info("Configuring IPSec Connections")

        ipsec_confs = env.get('ipsec_confs')
        needs_restart = False

        changed = self._configure_ipsec_networking()
        needs_restart = needs_restart or changed

        changed = self._configure_ipsec_base(ipsec_confs)
        needs_restart = needs_restart or changed

        changed = self._configure_ipsec_secrets(ipsec_confs)
        needs_restart = needs_restart or changed

        # Configure all of the individual sites
        for ipsec_name, ipsec_conf in ipsec_confs.items():
            changed = self._configure_ipsec_site(ipsec_name, ipsec_conf)
            needs_restart = needs_restart or changed

        if needs_restart:
            logger.info("IPsec conf changed. Restarting IPSec Service")
            with hide(*fab_output_hides):
                sudo('/etc/init.d/ipsec stop')
                sudo('/etc/init.d/ipsec start')
            return

        logger.info("IPsec conf not changed. No restart required")

    def _configure_ipsec_networking(self):
        """
        Configure ``/etc/sysctl.conf`` for ipsec networking.
        Return True if the file changed.
        """
        with hide(*fab_output_hides):
            changed = upload_template_changed(
                '../config/tpl/sysctl.conf',
                '/etc/sysctl.conf',
                use_sudo=True,
                mode=0600,
            )
            if changed:
                sudo('sysctl -p /etc/sysctl.conf')

        return changed

    def _configure_ipsec_base(self, ipsec_confs):
        """
        Configure ``/etc/ipsec.conf`` and return True if the file changed.

        Excludes all of the right side subnets from ``virtual_private`` so
        that they're properly sent to the remote tunnel.
        """
        base_conf_tpl = '../config/tpl/ipsec/ipsec.conf'
        subnet_exclusions = []

        for conf in ipsec_confs.values():
            subnet_exclusion = '%%v4:!%s' % conf['right_subnet']
            subnet_exclusions.append(subnet_exclusion)

        excluded_subnets = ','.join(subnet_exclusions)
        with hide(*fab_output_hides):
            return upload_template_changed(
                base_conf_tpl,
                '/etc/ipsec.conf',
                context={'excluded_subnets': excluded_subnets},
                use_sudo=True,
                mode=0600,
            )

    def _configure_ipsec_secrets(self, ipsec_confs):
        """
        Configure ``/etc/ipsec.secrets`` and return True if the file changed.
        """
        secrets_tpl = '../config/tpl/ipsec/ipsec.secrets'
        secret_confs = []

        for name, conf in ipsec_confs.items():
            secret_conf = {
                'right_public_ip': conf['right_public_ip'],
                'psk': env.get('ipsec_psk_%s' % name),
            }
            secret_confs.append(secret_conf)

        # Configure the /etc/ipsec.d/<name>.conf file with passwords
        with hide(*fab_output_hides):
            return upload_template_changed(
                secrets_tpl,
                '/etc/ipsec.secrets',
                context={'confs': secret_confs},
                use_sudo=True,
                mode=0600,
                use_jinja=True
            )

    def _configure_ipsec_site(self, name, confs):
        """
        Configure ``/etc/ipsec.d/<name>.conf`` and return True if the file
        changed.
        """
        site_conf_tpl = '../config/tpl/ipsec.d/_.conf'

        context = {
            'conn_name': name,
            'elastic_ip': env.aws_elastic_ip,
        }
        for key, value in confs.items():
            context[key] = value

        with hide(*fab_output_hides):
            return upload_template_changed(
                site_conf_tpl,
                '/etc/ipsec.d/%s.conf' % name,
                context=context,
                use_sudo=True,
                mode=0600,
            )

    def _fix_pstat_logging_perms(self):
        logger.info("Fixing log file permissions")
        # Fix python log file permissions
        with hide(*fab_output_hides):
            sudo('touch /var/log/pstat/ldap_logins.log')
            sudo('chown %s /var/log/pstat/ldap_logins.log' % F_CHOWN)

    def _enable_cron_tpl(self, cron_file):
        context = {
            'pstat_dir': os.path.join(env.project_root, 'pstat'),
            'python': PYTHON_BIN,
            'log_dir': LOG_DIR,
        }

        cron_dst_base = '/etc/cron.d'

        cron_tpl_path = os.path.join('../config/tpl/pstat/cron.d', cron_file)
        cron_dst_path = os.path.join(cron_dst_base, cron_file)

        upload_template(cron_tpl_path, cron_dst_path, context, use_sudo=True)
        sudo('chown root:root %s' % cron_dst_path)

    def _configure_pstat_cron_jobs(self):
        if not env.get('enable_pstat_cron_jobs', False):
            return

        logger.info("Configuring cron pstat_jobs")
        with hide(*fab_output_hides):
            self._enable_cron_tpl('pstat_jobs')

    def _configure_email_sending(self):
        if not env.get('enable_email_sending', False):
            return

        logger.info("Configuring cron pstat_mail")
        with hide(*fab_output_hides):
            self._enable_cron_tpl('pstat_mail')


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
    new_source_dir, current_source_dir=None, chown=None, chmod=None,
):
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
