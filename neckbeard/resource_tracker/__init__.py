import simpledb
from simpledb.models import FieldEncoder

# This is a hack so that we can patch the `InfrastructureNode` object in the
# correct place for the SimpleDBResourceTracker. Once we can stop doing this
# evil, this import should be from the proper place
from neckbeard.environment_manager import InfrastructureNode


def build_tracker_from_config(configuration_manager):
    """
    Use the `neckbeard` configuration from the given manager to instantiate the
    proper `ResourceTracker` class.
    """
    neckbeard_config = configuration_manager.get_neckbeard_meta_config()

    tracker_config = neckbeard_config['resource_tracker']
    tracker_path = tracker_config['path']
    tracker_init = tracker_config['init']

    if tracker_path == 'neckbeard.resource_tracker.SimpleDBResourceTracker':
        # This a horribly hacky way to load the chosen ResourceTracker.
        # Instead, we should use a plugin registration system to instantiate
        # these.
        return SimpleDBResourceTracker(**tracker_init)
    else:
        raise NotImplementedError()


class ResourceTrackerBase(object):
    """
    `ResourceTracker` objects are responsible for keeping tracking of cloud
    resources. It's the only real "memory" that persists between runs outside
    of the cloud APIs themselves. It tracks nodes, their deployment state,
    their generation and their environment.

    The `__init__` for a `ResourceTracker` will be passed as kwargs all of the
    configuration from `neckbeard_meta.resource_tracker.init`.
    """


class SimpleDBResourceTracker(ResourceTrackerBase):

    def __init__(self, domain, aws_access_key_id, aws_secret_access_key):
        self.domain = domain
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key

        self.initialize_backend()

    def initialize_backend(self):
        simpledbconn = simpledb.SimpleDB(
            # Evidently the connection can't deal with unicode keys
            str(self.aws_access_key_id),
            str(self.aws_secret_access_key),
        )

        domain_name = self.domain
        # Ensure the SimpleDB domain is created
        if not simpledbconn.has_domain(domain_name):
            simpledbconn.create_domain(domain_name)

        # Now we have to do some voodoo lifted from the metaclass
        #` simpledb.models:ModelMetaclass.__new__` so that all of the ORM magic
        # works
        # We have to do all of this nonsense so that we can avoid declaring the
        # SimpleDB connection object at class definition time and instead
        # declare it at the instantiation time of its environment manager
        simpledbconn.encoder = FieldEncoder(
            InfrastructureNode.fields,
        )

        domain = simpledb.Domain(
            domain_name,
            simpledbconn,
        )
        domain.model = InfrastructureNode

        class SimpleDBMeta:
            pass

        SimpleDBMeta.connection = simpledbconn
        SimpleDBMeta.domain = domain

        InfrastructureNode.Meta = SimpleDBMeta
