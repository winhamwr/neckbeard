
def build_tracker_from_config(configuration_manager):
    """
    Use the `neckbeard` configuration from the given manager to instantiate the
    proper `ResourceTracker` class.
    """
    neckbeard_config = configuration_manager.get_neckbeard_configuration()

    tracker_config = neckbeard_config['resource_tracker']
    backend_config = tracker_config['backend']
    backend_path = backend_config['path']

    if backend_path == 'neckbeard.resource_tracker.SimpleDBResourceTracker':
        # This a horribly hacky way to load the backend. Instead, we should use
        # a plugin registration system to instantiate these.
        return SimpleDBResourceTracker(
            domain=backend_config['domain'],
            aws_access_key_id=backend_config['aws_access_key_id'],
            aws_secret_access_key=backend_config['aws_secret_access_key'],
        )
    else:
        raise NotImplementedError()


class ResourceTrackerBase(object):
    """
    `ResourceTracker` objects are responsible for keeping tracking of cloud
    resources. It's the only real "memory" that persists between runs outside
    of the cloud APIs themselves. It tracks nodes, their deployment state,
    their generation and their environment.
    """
    pass


class SimpleDBResourceTracker(ResourceTrackerBase):
    pass
