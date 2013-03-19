

class ConfigurationManager(object):
    """
    ConfigurationManager accepts the already-parsed JSON configuration
    (probably from ``NeckbeardLoader``) and creates an expanded configuration
    for each individual `CloudResource` in an environment. It:
        * Validates the configuration for required options and internal
          consistency
        * Allows `resource_addons` and `environment_addons` to validate their
          specific slice of configuration
        * Generates and properly scopes the template context required for
          expanding individual configuration options. eg.
            * environment.constants
            * environment.secrets
            * seed_environment.constants
            * seed_environment.secrets
            * node
            * seed_node
        * Determines the current scaling state for each `scaling_group` to
          determine how many nodes should exist
          (using the `ScalingCoordinator`).
        * The end results combines the scaling state, configuration, and
          context to generate an individual expanded configuration for each
          `CloudResource` that should exist.
    """
    def __init__(self,
                 constants, secrets, secrets_tpl, environments, node_templates):
        self.constants = constants
        self.secrets = secrets
        self.secrets_tpl = secrets_tpl
        self.environments = environments
        self.node_templates = node_templates

    def is_valid(self):
        pass

    def print_validation_errors(self):
        pass

    def _get_constants(self, environment):
        environments = self.constants.get('environments', {})
        return environments.get(environment, {})

    def _get_secrets(self, environment):
        environments = self.secrets.get('environments', {})
        return environments.get(environment, {})

    def expand_configurations(self):
        pass

    def dump_node_configuration(self, output_directory):
        pass


class CloudResourceConfiguration(object):
    """
    `CloudResourceConfiguration` is responsible for turning an individual
    resource configuration from an environment, applying any `node_templates`,
    and applying the configuration context to all configuration values. The end
    result is an expanded configuration for its specific `CloudResource`.
    """
    def __init__(self, node_config, node_templates, config_context):
        pass

    def is_valid(self):
        pass

    def get_expanded_configurations(self):
        pass

