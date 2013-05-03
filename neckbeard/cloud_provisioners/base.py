import logging
import sys

logger = logging.getLogger('deploy:base')
logger.setLevel(logging.INFO)


def import_class(module_name):
    """
    Import a module with a reasonable traceback and return that module as the
    variable.

    eg. dumps = import_class('simplejson.dumps')
    if dumps is None:
        dumps = import_class('json.dumps')

    Reference: http://lucumr.pocoo.org/2011/9/21/python-import-blackbox/
    Written by: Armin Ronacher
    """

    module, klass = module_name.rsplit('.', 1)
    try:
        __import__(module)
    except ImportError:
        exc_type, exc_value, tb_root = sys.exc_info()
        logger.warning(exc_type)
        logger.warning(exc_value)
        tb = tb_root
        while tb is not None:
            if tb.tb_frame.f_globals.get('__name__') == module:
                raise exc_type, exc_value, tb_root
            tb = tb.tb_next
        return None
    return getattr(sys.modules[module], klass)


class BaseNodeDeployment(object):
    """
    The base deployer object from which all specialized deployers should
    inherit. This class defines the interface that should be implemented by
    other specialized deployers.

    A ``Deployer`` performs all of the actions to create a server/node and
    configure that node so that a ``Provisioner`` can handle SSHing in to that
    server and actually configure packages/directories/services etc.. A
    ``Deployer`` does things like spinning up ec2 instances, getting data from
    backups to populate that instance, mounting EBS volumes and attaching
    elastic IPs.
    """
    def __init__(
        self,
        deployment,
        seed_deployment,
        is_active,
        aws_type,
        node_name,
        seed_node_name,
        brain_wrinkles,
        conf,
        seed_verification=False,
        *args,
        **kwargs
    ):
        self.deployment = deployment
        self.seed_deployment = seed_deployment
        self.is_active = is_active
        self.aws_type = aws_type
        self.node_name = node_name
        self.seed_node_name = seed_node_name
        self._conf = conf
        self.seed_verification = seed_verification

        # TODO: Support more than one brain wrinkle
        brain_wrinkle = brain_wrinkles[brain_wrinkles.keys()[0]]
        brain_wrinkle_kls = import_class(brain_wrinkle['path'])
        if brain_wrinkle_kls is None:
            logger.critical(
                "No brain wrinkle class located at <%s>",
                brain_wrinkle['path'],
            )
            exit(1)

        self.node = self.get_node()

        self.provisioner = brain_wrinkle_kls(
            node=self.node,
            conf=conf,
            **brain_wrinkle.get('init', {}))

        self.seed_node = None
        if self.seed_deployment:
            self.seed_node = self.seed_deployment.get_active_node(
                self.aws_type, self.seed_node_name)

        # Whether or not this is the first time we're running deployment
        # on this node. We can be running initial deploy on already-provisioned
        # nodes or nodes that we're provisioning for the first time
        self.initial_deploy_complete = False

    def ensure_node_created(self):
        """
        Ensure that the node already exists, and if it doesn't, create it.
        """
        if not self.node:
            # Creating new node
            self.get_seed_data()
            self.node = self.create_new_node()
        if self.node.initial_deploy_complete:
            self.initial_deploy_complete = True

    def run(self):
        self.ensure_node_created()
        self.deploy(self.node, first_run=not self.initial_deploy_complete)
        if self.seed_verification and not self.initial_deploy_complete:
            self.verify_seed_data(self.node)

        self.node.set_initial_deploy_complete()

    def get_seed_data(self):
        """
        Gather the seed data with which to start the node.

        EBS snapshots, SQL dumps, file archives, etc.
        """
        pass

    def verify_seed_data(self, node):
        """
        Verify that the seed data was properly loaded.
        """
        pass

    def wait_until_created(self, node):
        """
        Sleep/Block until this node exists and can be interacted with.
        """
        pass

    def creation_complete(self, node):
        """
        Returns True if the given ``node`` has been created and is ready for
        interaction.
        """
        pass

    def create_new_node(self):
        """
        Actually instantiate a new node. This might spin up an ec2/rds instance
        or provision a VM.
        """
        pass

    def deploy(self, node, first_run=False):
        """
        Actually deploy against this node using the configured ``Provisioner``.
        Package installation, code-pushing, service restarts etc. happen in
        this step via the ``Provisioner``.
        """
        pass

    def get_node(self):
        """
        Get the node to which we're deploying based on the configured
        deployment and generation.
        """
        if self.is_active:
            return self.deployment.get_active_node(
                self.aws_type, self.node_name)
        else:
            return self.deployment.get_pending_node(
                self.aws_type, self.node_name)
