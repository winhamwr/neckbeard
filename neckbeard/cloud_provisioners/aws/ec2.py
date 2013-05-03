"""
Deployment configuration for an ec2 app server node. AWS-specific configuration
and actions live here while generic actions/configurations live at
``pstat.pstat_deploy.node_actions.app_provisioner``
"""
import ConfigParser
import logging
import os.path
import time
from collections import namedtuple, defaultdict
from tempfile import NamedTemporaryFile

from boto import ec2
from fabric.api import sudo, env, require, put, hide, run
from fabric.contrib.files import upload_template

from neckbeard.cloud_provisioners import BaseNodeDeployment
from neckbeard.output import fab_out_opts

LOG_DIR = '/var/log/pstat'
AWS_METADATA_SERVICE = 'http://169.254.169.254/latest/meta-data/'
LAUNCH_REFRESH = 15  # seconds to wait before re-checking ec2 statuses

logger = logging.getLogger('aws.ec2')

fab_output_hides = fab_out_opts[logger.getEffectiveLevel()]
fab_quiet = fab_output_hides + ['stderr']

EC2_FSTAB_TPL = (
    """
    # /etc/fstab: static file system information.
    # <device>  <mount_point>  <fs_type>  <options>  <dump_freq>  <pass_num>
    {% for entry in fstab_entries -%}
    """
    "{{ entry.device_name}} {{ entry.mount_point}} {{ entry.fs_type }} "
    "{{ entry.options }} {{ entry.dump_freq}} {{ entry.pass_num}}"
    """
    """
    "{%- endfor %}"
)
fstabEntry = namedtuple(
    'fstabEntry',
    [
        'device_name',
        'mount_point',
        'fs_type',
        'options',
        'dump_freq',
        'pass_num',
    ]
)
EC2_FSTAB_DEFAULTS = [
    fstabEntry('proc', '/proc', 'proc', 'nodev,noexec,nosuid', '0', '0'),
    fstabEntry('LABEL=cloudimg-rootfs', '/', 'ext3', 'defaults', '0', '0'),
    fstabEntry(
        '/dev/sda2',
        '/mnt',
        'auto',
        'defaults,nobootwait,comment=cloudconfig',
        '0',
        '0',
    ),
    fstabEntry(
        '/dev/sda3',
        'none',
        'swap',
        'sw,comment=cloudconfig',
        '0',
        '0',
    ),
]


class Ec2NodeDeployment(BaseNodeDeployment):
    """
    Deployment controller for an ec2 appserver nodes. Deals with the
    AWS-specific configuration actions and delegates system-level configuration
    to the provisioner.
    """

    def __init__(self, *args, **kwargs):
        """
        ``conf[ebs]`` is a dictionary mapping out exactly where and how any EBS
        volumes should be attached, formatted and mounted, along with any
        system directories that need to be symlinked to live on the EBS volume.

        eg.

            ebs_confs = {
                'vols': {
                    'fs': {
                        'device': '/dev/sdf',
                        'filesystem': 'xfs',
                        'size': 50, # Size in GB
                        'mount_point': '/vol/fs',
                        'ebs_bound_dirs': [
                            {
                                'bind_path': '/var/log/pstat',
                                'src_path': '/vol/fs/var/log/pstat',
                            },
                            {
                                'bind_path': '/var/log/celery',
                                'src_path': '/vol/fs/var/log/celery',
                            },
                        ],
                    },
                },
            }
        """
        conf = kwargs['conf']
        self.ebs_confs = conf.get('ebs', {'vols': {}})

        super(Ec2NodeDeployment, self).__init__(*args, **kwargs)

        # A volume-label keyed dictionary with EBS seed snapshot ids
        # eg. {'logs': 'snap-xxxxxxx'}
        self.seed_ebs_snapshots = {}
        # A volume-label keyed dictionary with the attached EBS volume id
        # eg. {'fs': 'vol-xxxxxxx'}
        self.attached_volumes = {}

    def get_seed_data(self):
        """
        Gather the seed data with which to start the node.
        """
        if not self.seed_deployment:
            return
        require('aws_access_key_id')
        require('aws_secret_access_key')

        self.seed_ebs_snapshots = self._get_seed_ebs_snapshots()

    def wait_until_created(self, node):
        while not self.creation_complete(node):
            logging.info("Instance pending. Waiting %ss", LAUNCH_REFRESH)
            time.sleep(LAUNCH_REFRESH)

    def creation_complete(self, node):
        start_host_string = env.host_string
        start_host = env.host
        node.refresh_boto_instance()
        if node.boto_instance.state == 'running':
            # Try to SSH in to test that it's actually available
            timeout = 60  # 1 minute
            tries = 0
            step = LAUNCH_REFRESH
            while tries * step <= timeout:
                node.refresh_boto_instance()
                env.host_string = node.boto_instance.public_dns_name
                env.host = node.boto_instance.public_dns_name
                tries += 1
                try:
                    with hide('everything'):
                        sudo('uptime', pty=True)
                    env.host_string = start_host_string
                    env.host = start_host
                    return True
                except:
                    logger.info(
                        "%s not ready for SSH. Waiting %ss",
                        node.boto_instance.public_dns_name,
                        LAUNCH_REFRESH)
                    time.sleep(LAUNCH_REFRESH)

        env.host_string = start_host_string
        env.host = start_host
        return False

    def create_new_node(self):
        """
        Launch a new ec2 instance from the appropriate AMI and configure any
        EBS volumes and first-run-only configurations.
        """
        logger.info("Launching new ec2 instance")
        ec2_instance = self.launch()

        if self.is_active:
            self.deployment.set_active_node(
                'ec2', env.node_name, ec2_instance)
        else:
            self.deployment.set_pending_node(
                'ec2', env.node_name, ec2_instance)

        # Build EBS volumes, unless explicitly told not to.
        ebs_debug = self.ebs_confs.get('debug', {})
        if not ebs_debug.get('attach_ebs_volumes', True):
            logger.warning("Debug ebs_conf found")
            logger.warning("Not attaching configured EBS volumes.")

            return self.get_node()

        vol_confs = self.ebs_confs.get('vols', {})
        self.attached_volumes = self._attach_ebs_vols(
            ec2_instance_id=ec2_instance.id,
            vol_confs=vol_confs,
            seed_ebs_snapshots=self.seed_ebs_snapshots)

        # TODO: Find a way to move this fstab stuff to the normal deploy
        # Otherwise, we're reducing our ability to parallelize node
        # creation. If we use new fabric to actually parallelize the
        # create_new_node deploy process, then this isn't actually a big
        # deal, though.
        node = self.get_node()
        self.wait_until_created(node)

        # Ensure we're running commands against our spanking-new instance
        node.refresh_boto_instance()
        env.host_string = node.boto_instance.public_dns_name

        self._ensure_ebs_vols_mounted(ec2_instance.id, vol_confs)

        return self.get_node()

    def deploy(self, node, first_run=False):
        logger.info("Deploying to instance: %s" % node)
        self.wait_until_created(node)

        # RDS vs non-RDS configuration
        env.db_host = 'localhost'
        env.db_master_user = 'root'
        env.db_master_password = ''
        rds_node = self._get_masterdb()
        if rds_node:
            env.db_host, _ = rds_node.boto_instance.endpoint  # (Host, Port)
            env.db_master_user = rds_node.boto_instance.master_username
            env.db_master_password = env.rds_master_password

        # Set fab parameters based on the ec2 instance
        env.hosts = [node.boto_instance.public_dns_name]
        env.host_string = node.boto_instance.public_dns_name
        env.host = node.boto_instance.public_dns_name

        env.hostname = '%s-%s' % (env.get('env'), env.get('node_name'))
        env.ec2_instance_id = node.boto_instance.id

        if first_run:
            ebs_confs = self.ebs_confs
            ebs_debug = ebs_confs.get('debug', {})
            if ebs_debug.get('attach_ebs_volumes', True):
                # Create the .ec2tools configuration for snapshotting/backups
                self._configure_ec2tools(
                    self.deployment.ec2conn,
                    node.boto_instance.id,
                    self.ebs_confs['vols'])
                if ebs_confs.get('do_snapshot_backups', False):
                    self._configure_ebs_backup(
                        '/opt/pstat/versions/current/pstat',
                        '/home/policystat/env/bin/python',
                        '/vol/fs/pstat_storage',
                    )

            else:
                logger.warning(
                    "Debug ebs_conf found with 'attach_ebs_volumes' False")
                logger.warning("Not configuring ec2tools or backups.")

            # Fix file permissions
            logger.info(
                "Fixing file permissions and starting stopped services")
            self.provisioner.stop_services()
            self.provisioner.fix_folder_perms()
            self.provisioner.start_services()

        node_role_map = self._get_node_role_map()

        self.provisioner.do_update(
            node_role_map=node_role_map,
            node_roles=node._deployment_info.get('roles', []),
            first_run=not self.initial_deploy_complete,
        )

    def _get_node_role_map(self):
        """
        Get a dictionary with mappings of roles and boto ec2 instances in the
        same availability zone and all nodes with the role.

        Eg. {
            'memcached': {
                'same_az': [foo1],
                'all': [foo1, foo2]
            }
        }
        """
        def _role_map():
            return {'same_az': [], 'all': []}

        nodes_by_role = defaultdict(_role_map)

        if self.is_active:
            nodes = self.deployment.get_all_active_nodes(is_running=1)
        else:
            nodes = self.deployment.get_all_pending_nodes(is_running=1)

        deploy_node = self.get_node()
        local_az = deploy_node.boto_instance.placement

        for node in [n for n in nodes if n.aws_type == 'ec2']:
            node_confs = self.deployment.deployment_confs['ec2'][node.name]
            roles = node_confs.get('roles', [])
            for role in roles:
                nodes_by_role[role]['all'].append(node)
                if node.boto_instance.placement == local_az:
                    nodes_by_role[role]['same_az'].append(node)

        return nodes_by_role

    def _get_debug_seed_snapshot(self, vol_label):
        """
        Determine if the ebs_confs is configured in debug mode and has a seed
        snapshot for the given `vol_label`.

        Returns the snapshot_id if it exists, None otherwise.
        """
        ebs_debug = self.ebs_confs.get('debug', {})
        if not ebs_debug:
            return None

        vols_debug = ebs_debug.get('vols', {})
        vol_debug = vols_debug.get(vol_label, None)
        return vol_debug

    def _get_seed_ebs_snapshots(self):
        """
        Take snapshots of the seed EBS volumes to use as sources for new EBS
        volumes.

        Returns a dictionary of volume names and their snapshot ids.
        """
        logger.info(u"Determining seed EBS snapshots")
        # Perform EBS snapshots on the configured volumes

        seed_snapshots = {}
        for volume_name, volume_conf in self.ebs_confs['vols'].items():
            snapshot_id = self._get_debug_seed_snapshot(volume_name)
            if snapshot_id is None:
                env.host_string = self.seed_node.boto_instance.public_dns_name
                snapshot_id = self._get_ebs_snapshot(volume_name, volume_conf)
            else:
                logger.info(
                    "Using hard-coded debug snapshot_id %s for volume: %s",
                    snapshot_id,
                    volume_name
                )

            seed_snapshots[volume_name] = snapshot_id

        return seed_snapshots

    def _install_ec2_consistent_snapshot(self):
        """
        Install the ec2-consistent-snapshot utility to handle xfs freezing and
        unfreezing.

        https://github.com/alestic/ec2-consistent-snapshot
        """
        with hide(*fab_quiet):
            install_check = run('which ec2-consistent-snapshot')
        if install_check.return_code != 0:
            logger.info("Installing ec2-consistent-snapshot")

            with hide(*fab_output_hides):
                sudo('add-apt-repository ppa:alestic')
                sudo('apt-get update')
                sudo('apt-get install ec2-consistent-snapshot -y')

    def _get_ebs_snapshot(self, volume_name, volume_conf):
        """
        Take a snapshot on the current host of the EBS volume corresponding to
        ``volume_name`` and return the snapshot id.
        """
        self._install_ec2_consistent_snapshot()

        # Need to take a snapshot for use
        logger.info(u"Snapshotting EBS vols from %s", env.host_string)

        if volume_conf['filesystem'] != 'xfs':
            raise NotImplementedError("Only XFS EBS vols are supported")

        # Find the volume id of the appropriate seed EBS volume
        device = volume_conf['device']
        seed_volume = _get_attached_volume(
            self.seed_deployment.ec2conn,
            self.seed_node.boto_instance.id,
            device)

        if seed_volume is None:
            # No seed volume with matching device found
            logger.critical("No seed volume on device %s found", device)
            exit(1)

        # Build the ec2-consistent-snapshot command to take the snapshot for
        # the appropriate volume
        mount_point = volume_conf['mount_point']
        cmd_tpl = (
            'ec2-consistent-snapshot '
            '--freeze-filesystem %(mount_point)s '
            '--description '
            '"seed from %(seed_deploy)s-%(seed_node)s to %(deploy)s-%(node)s" '
            '--aws-access-key-id %(aws_access_key_id)s '
            '--aws-secret-access-key %(aws_secret_access_key)s '
            '%(volume_id)s '
        )
        context = {
            'mount_point': mount_point,
            'seed_deploy': self.seed_deployment.deployment_name,
            'seed_node': self.seed_node_name,
            'deploy': self.deployment.deployment_name,
            'node': self.node_name,
            'aws_access_key_id': env.aws_access_key_id,
            'aws_secret_access_key': env.aws_secret_access_key,
            'volume_id': seed_volume.id,
        }
        cmd = cmd_tpl % context

        with hide(*fab_output_hides):
            snapshot_result = sudo(cmd)
            if snapshot_result.return_code != 0:
                logger.critical("Error creating seed snapshot")
                logger.critical("Output: %s", snapshot_result)
                exit(1)

        # eg. snap-aaaabbbb
        assert len(str(snapshot_result)) == 13

        return str(snapshot_result)

    def _get_masterdb(self):
        """
        Get the rds masterdb node for this deployment.
        """
        if self.is_active:
            return self.deployment.get_active_node('rds', 'masterdb')
        else:
            return self.deployment.get_pending_node('rds', 'masterdb')

    def _attach_ebs_vols(self, ec2_instance_id, vol_confs, seed_ebs_snapshots):
        """
        Attach the appropriate EBS volumes to the ``ec2_instance`` and wait
        for them to complete.
        """
        require('aws_availability_zone')

        with hide(*fab_quiet):
            logger.info("Attaching EBS volumes from snapshots")
            attached_volumes = create_and_attach_ebs_vols(
                ec2conn=self.deployment.ec2conn,
                availability_zone=env.aws_availability_zone,
                instance_id=ec2_instance_id,
                vol_confs=vol_confs,
                seed_ebs_snapshots=seed_ebs_snapshots)

            env.attached_volumes = True

            return attached_volumes

    def _ensure_ebs_vols_mounted(self, ec2_instance_id, vol_confs):
        """
        Ensure that the EBS volumes are succesfully mounted and any required
        directory symlinks are in place.
        """
        self.provisioner.stop_services()

        self._update_fstab(vol_confs)

        with hide(*fab_quiet):
            for vol_label, vol_conf in vol_confs.items():
                self._ensure_ebs_vol_mounted(
                    ec2_instance_id,
                    vol_label,
                    vol_conf,
                )

    def _update_fstab(self, vol_configs):
        """
        Update /etc/fstab to include the configured EBS volumes and all of
        their bound directories.
        """
        # Load the /etc/fstab template and the ec2 defaults
        fstab_entries = []
        fstab_entries.extend(EC2_FSTAB_DEFAULTS)

        # Add entries for all attached volumes
        for vol_label, vol_conf in vol_configs.items():
            logger.info("Configuring fstab entries for %s", vol_label)
            # Configure the mount point for the whole volume
            fstab_entries.append(
                fstabEntry(
                    device_name=vol_conf['device'],
                    mount_point=vol_conf['mount_point'],
                    fs_type=vol_conf['filesystem'],
                    options='noatime',
                    dump_freq=0,
                    pass_num=0,
                )
            )

            # Configure all of the bound directories
            for ebs_bind_confs in vol_conf['ebs_bound_dirs']:
                # Add a directory bind line
                # eg. /vol/fs/var/log/pstat /var/log/pstat none bind 0 0
                fstab_entries.append(
                    fstabEntry(
                        device_name=ebs_bind_confs['src_path'],
                        mount_point=ebs_bind_confs['bind_path'],
                        fs_type='none',
                        options='bind',
                        dump_freq=0,
                        pass_num=0,
                    )
                )

        # Push the /etc/fstab file to the server
        with NamedTemporaryFile() as fstab_tpl_f:
            fstab_tpl_f.write(EC2_FSTAB_TPL)
            fstab_tpl_f.flush()
            context = {
                'fstab_entries': fstab_entries,
            }
            tpl_dir, tpl_name = os.path.split(fstab_tpl_f.name)
            with hide(*fab_output_hides):
                upload_template(
                    tpl_name,
                    '/etc/fstab',
                    context=context,
                    use_jinja=True,
                    template_dir=tpl_dir,
                    mode=644,
                    use_sudo=True,
                )

    def _ensure_ebs_vol_mounted(self, ec2_instance_id, vol_label, vol_config):
        """
        Ensure a single EBS volume is succesfully mounted and any required
        fstab directory binds are in place.
        """
        with hide(*fab_quiet):
            # Wait for the volume attachment to complete
            logger.info(
                "Waiting for EBS volume %s to attach to device %s",
                vol_label,
                vol_config['device']
            )

            # ``stat`` on the device until it exists
            stat_result = sudo('stat %s' % vol_config['device'])
            while stat_result.return_code != 0:
                logger.info(
                    "Attachment pending. Waiting %s seconds.",
                    LAUNCH_REFRESH,
                )
                time.sleep(LAUNCH_REFRESH)
                stat_result = sudo('stat %s' % vol_config['device'])

            # Ensure all of the EBS fstab binds are configured
            logger.info("Binding/Mounting EBS directories")

            if vol_config['filesystem'] != 'xfs':
                raise NotImplementedError(
                    "Only the xfs filesystem is implemented")

            # Mount the EBS volume
            sudo("mkdir %s --parent" % vol_config['mount_point'])
            with hide(*fab_quiet):
                sudo("mount %s" % vol_config['mount_point'])

            # Mount all of the bound folders
            for ebs_bind_confs in vol_config['ebs_bound_dirs']:
                src_path = ebs_bind_confs['src_path']
                bind_path = ebs_bind_confs['bind_path']
                sudo('mkdir %s --parent' % bind_path)
                sudo('mkdir %s --parent' % src_path)
                logger.info(
                    "Mounting bound dir %s to %s",
                    src_path,
                    bind_path,
                )
                mount_result = sudo('mount %s' % bind_path)
                if mount_result.failed:
                    logger.warning(
                        "Error mounting %s. Msg: %s",
                        bind_path,
                        mount_result)
                else:
                    # If the mount succeeded, optionally fix directory
                    # permissions and ownership
                    uid = ebs_bind_confs.get('uid', '')
                    gid = ebs_bind_confs.get('gid', '')
                    mode = ebs_bind_confs.get('mode', '')
                    if mode:
                        logger.info(
                            "Fixing directory mode on %s to %s",
                            bind_path,
                            mode,
                        )
                        sudo('chmod %s %s' % (mode, bind_path))
                    if uid or gid:
                        ownership = "%s:%s" % (uid, gid)
                        logger.info(
                            "Changing ownership of %s to %s",
                            bind_path,
                            ownership,
                        )
                        sudo('chown %s %s' % (ownership, bind_path))

            if vol_config['filesystem'] == 'xfs':
                # Grow the file systems if needed
                logger.info("Growing the file system")
                with hide(*fab_quiet):
                    sudo('xfs_growfs %s' % vol_config['mount_point'])

    def _configure_ec2tools(self, ec2conn, ec2_instance_id, vol_confs):
        """
        Configure the django-ec2tools configuration file for backing up
        EBS volumes.
        """
        logger.info("Configuring /root/.ec2tools.ini")
        config = ConfigParser.ConfigParser()
        config.add_section('volume_aliases')
        for vol_label in vol_confs.keys():
            config.set('volume_aliases', vol_label, vol_label)

        for vol_label, vol_conf in vol_confs.items():
            attached_vol = _get_attached_volume(
                ec2conn, ec2_instance_id, vol_conf['device'])

            config.add_section(vol_label)
            config.set(vol_label, 'volume_id', attached_vol.id)
            config.set(vol_label, 'mountpoint', vol_conf['mount_point'])

        with NamedTemporaryFile() as ec2_file:
            config.write(ec2_file)
            ec2_file.file.flush()
            with hide(*fab_output_hides):
                put(ec2_file.name, '/tmp/.ec2tools.ini')
                sudo('mv /tmp/.ec2tools.ini /root/')

    def _configure_ebs_backup(self, manage_dir, python_file, storage_dir):
        """
        Configure cronjob to perform EBS backup for the configured volumes
        using django-ec2tools.
        """
        logger.info("Configuring EBS snapshotting via django-ec2tools")
        minutes = ['10']
        user = 'root'

        cmd_dict = {
            'manage_dir': manage_dir,
            'python_file': python_file,
            'storage_dir': storage_dir,
            'log_dir': LOG_DIR,
        }
        cmd_tpl = 'cd %(manage_dir)s && \
        %(python_file)s manage.py ec2_take_snapshot \
        --config-file=/root/.ec2tools.ini fs >> \
        %(storage_dir)s/snapshot_backup.log 2>&1'
        cmd = cmd_tpl % cmd_dict

        cron_tpl = '%(time)s %(user)s %(cmd)s'
        time_tpl = '%(minutes)s %(hours)s * * %(dow)s'

        # Prime time backups
        hours = [str(n) for n in range(8, 18)]
        dow = ['mon', 'tue', 'wed', 'thu', 'fri']

        time_dict = {
            'minutes': ','.join(minutes),
            'hours': ','.join(hours),
            'dow': ','.join(dow),
        }
        time_conf = time_tpl % time_dict

        cron = cron_tpl % {'time': time_conf, 'user': user, 'cmd': cmd}
        fname = 'ebs_backup_prime'

        sudo('rm /etc/cron.d/%s' % fname)
        sudo('echo "%s" > /etc/cron.d/%s' % (cron, fname))

        # Off hour backups
        hours = ['4']
        dow = ['*']

        time_dict = {
            'minutes': ','.join(minutes),
            'hours': ','.join(hours),
            'dow': ','.join(dow)
        }
        time_conf = time_tpl % time_dict

        cron = cron_tpl % {'time': time_conf, 'user': user, 'cmd': cmd}
        fname = 'ebs_backup_off'

        sudo('rm /etc/cron.d/%s' % fname)
        sudo('echo "%s" > /etc/cron.d/%s' % (cron, fname))

        # Configure backup pruning
        cmd_tpl = (
            'cd %(manage_dir)s && '
            '%(python_file)s manage.py ec2_prune_snapshots '
            '--config-file=/root/.ec2tools.ini '
            '--all '
            '--strategy twoday_rolling_parent '
            '>> %(log_dir)s/snapshot_pruning.log 2>&1'
        )
        cmd = cmd_tpl % cmd_dict

        time_dict = {
            'minutes': 15,
            'hours': 3,
            'dow': '*',
        }
        time_conf = time_tpl % time_dict

        cron = cron_tpl % {'time': time_conf, 'user': user, 'cmd': cmd}
        fname = 'ebs_snapshot_pruning'

        sudo('rm /etc/cron.d/%s' % fname)
        sudo('echo "%s" > /etc/cron.d/%s' % (cron, fname))

        # Configure snapshot limit monitoring
        cmd_tpl = 'cd %(manage_dir)s && \
        %(python_file)s manage.py ec2_check_snapshot_limit >> \
        %(log_dir)s/snapshot_checker.log 2>&1'
        cmd = cmd_tpl % cmd_dict

        time_dict = {
            'minutes': 20,
            'hours': 3,
            'dow': '*',
        }
        time_conf = time_tpl % time_dict

        cron = cron_tpl % {'time': time_conf, 'user': user, 'cmd': cmd}
        fname = 'ebs_snapshot_checker'

        sudo('rm /etc/cron.d/%s' % fname)
        sudo('echo "%s" > /etc/cron.d/%s' % (cron, fname))

    def launch(self):
        """
        Launch a new EC2 instance

        Returns the boto ec2 instance.
        """
        require('aws_access_key_id')
        require('aws_secret_access_key')
        require('ami_id')
        require('aws_availability_zone')
        require('config_bucket')
        require('ec2_instance_type')

        ec2conn = self.deployment.ec2conn

        # Start a new ec2 instance and get its instance id
        reservation = ec2conn.run_instances(
            env.ami_id,
            key_name=self.config['aws']['keypair'],
            placement=env.aws_availability_zone,
            instance_type=env.ec2_instance_type,
            security_groups=env.aws_security_groups,
        )

        instance = reservation.instances[0]

        logging.info("Instance launching with id: %s", instance.id)

        return instance


def _get_public_ip():
    ip = sudo('curl -s %slocal-ipv4' % AWS_METADATA_SERVICE)
    return ip.strip()


def _delete_volumes(ec2conn, vols):
    logger.info(u"Detaching all volumes")
    for vol in vols:
        try:
            vol.detach()
        except:
            pass

    logger.info(u"Sleeping for 5 to finish attachment")
    time.sleep(5)
    vols = ec2conn.get_all_volumes(volume_ids=[v.id for v in vols])

    retry_limit = 20
    for vol in vols:
        retry_count = 0
        while not vol.status == 'available':
            if retry_count > retry_limit:
                logger.info(u"Retry limit reach. Detaching with --force")
                ec2conn.detach_volume(vol.id, force=True)
                retry_count = 0
            logger.info(
                u"vol: [%s] still pending. Trying again in 5 seconds",
                vol.id)
            time.sleep(5)
            updated_vols = ec2conn.get_all_volumes(volume_ids=[vol.id])
            vol = updated_vols[0]
            retry_count += 1

        logger.info(u"vol: [%s] succesfully detached" % vol.id)

    logger.info(u"Deleting the volumes")
    for vol in vols:
        try:
            vol.delete()
        except:
            # Give it one chance to wait 10 seconds and try again
            logger.info("Deletion failed for [%s]. Waiting 10s" % vol.id)
            time.sleep(10)
            vol.delete()


def create_and_attach_ebs_vols(
    ec2conn,
    availability_zone,
    instance_id,
    vol_confs,
    seed_ebs_snapshots,
):
    """
    Attach EBS volumes corresponding to the given volume configurations.

    ``vol_confs`` is ``vols`` item of the ``ebs_confs`` configuration
    dictionary.
    ``seed_ebs_snapshots`` is the ``Ec2NodeDeployments.seed_ebs_snapshots``
    dictionary with volume labels and their starting snapshot.

    Returns a dictionary of {<vol_label>: <boto_ebs_volume>} pairs.

    The function **does not** wait until attachment is 100% complete.
    """
    attached_ebs_vols = {}

    for vol_label, vol_conf in vol_confs.items():
        # First make sure we hadn't already attached this volume previously
        device = vol_conf['device']
        attached_volume = _get_attached_volume(ec2conn, instance_id, device)
        if attached_volume:
            logger.warning(
                "Volume %s with id already mounted on %s. Skipping",
                vol_label,
                attached_volume.id,
                device,
            )
            continue

        # Get the seed snapshot
        seed_snapshot_id = seed_ebs_snapshots.get(vol_label)
        seed_snapshot = None
        if seed_snapshot_id:
            seed_snapshot = ec2.snapshot.Snapshot(ec2conn)
            seed_snapshot.id = seed_snapshot_id

        if seed_snapshot:
            # Ensure the seed snapshot is 'completed' before trying to create
            # a new EBS volume
            logger.info(
                u"Ensuring that the %s snapshot is complete", vol_label)

            seed_snapshot.update()
            while seed_snapshot.progress != '100%':
                logger.info(
                    "snapshot: [%s] only %s percent complete. Waiting 5s",
                    seed_snapshot.id,
                    seed_snapshot.progress)
                time.sleep(5)
                seed_snapshot.update()

        # Create and attach the EBS volume based on the snapshot (if any)
        logger.info(u"Creating and attaching the %s EBS volume", vol_label)
        ebs_vol = create_and_attach_ebs_vol(
            ec2conn,
            availability_zone,
            instance_id,
            seed_snapshot_id,
            vol_conf['size'],
            vol_conf['device'],
        )

        attached_ebs_vols[vol_label] = ebs_vol

    return attached_ebs_vols


def create_and_attach_ebs_vol(
    ec2conn, availability_zone, instance_id, seed_snapshot_id, size, device,
):
    """
    Create and attach a volume to an instance, while tolerating some common ec2
    errors.

    Doesn't wait for the attachment to complete.

    Returns the boto ebs volume object.
    """
    # Make a volume using the seed snapshot if given
    vol = None
    while not vol:
        try:
            if seed_snapshot_id:
                logger.info(
                    u"Creating an EBS volume from snapshot [%s]",
                    seed_snapshot_id
                )
                vol = ec2conn.create_volume(
                    size,
                    availability_zone,
                    snapshot=seed_snapshot_id)
            else:
                logger.info(u"Creating a new blank EBS volume")
                vol = ec2conn.create_volume(
                    size,
                    availability_zone)
        except:
            logging.info(
                "Error trying to create the volume for device [%s]",
                device)
            logging.info("Sleeping for [%s] and trying again", LAUNCH_REFRESH)
            time.sleep(LAUNCH_REFRESH)

    # Attach the volume, waiting until the volume is available first
    while not vol.status == 'available':
        logger.info(
            "vol [%s] still pending. Trying again in %ss",
            vol.id,
            LAUNCH_REFRESH)
        time.sleep(LAUNCH_REFRESH)
        vols = ec2conn.get_all_volumes(volume_ids=[vol.id])
        vol = vols[0]

    # First Instance in the first Reservation
    instance = ec2conn.get_all_instances(
        instance_ids=[instance_id])[0].instances[0]
    while instance.state != 'running':
        logger.info(
            "Waiting until ec2 instance %s is running for EBS attachment",
            instance_id)
        time.sleep(LAUNCH_REFRESH)
        instance.update()

    logger.info("Attaching the volume [%s] to [%s]", vol.id, device)
    attached = False
    while not attached:
        try:
            ec2conn.attach_volume(vol.id, instance_id, device=device)
            attached = True
            logger.info(
                "Successfully attached volume [%s] to [%s]",
                vol.id,
                device)
        except Exception, e:
            logger.warning(e)
            logger.warning(
                "Error attaching volume [%s] to instance [%s] on device [%s]",
                vol.id,
                instance_id,
                device)
            logger.info("Waiting %ss and retrying", LAUNCH_REFRESH)
            time.sleep(LAUNCH_REFRESH)

    return vol


def _get_attached_volumes(ec2conn, ec2_instance_id):
    attached_vols = []

    volumes = ec2conn.get_all_volumes()
    for volume in volumes:
        if volume.attach_data \
           and volume.attach_data.instance_id == ec2_instance_id:
            attached_vols.append(volume)

    return attached_vols


def _get_attached_volume(ec2conn, ec2_instance_id, device):
    """
    Get the EBS volume attached to the given instance as the given
    ``device``.

    Returns None if no matching volume exists.
    """
    attached_vols = _get_attached_volumes(ec2conn, ec2_instance_id)

    for attached_vol in attached_vols:
        # Find the correct device
        if attached_vol.attach_data.device == device:
            return attached_vol

    return None
