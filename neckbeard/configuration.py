

class ConfigurationManager(object):
    """
    ConfigurationManager accepts the already-parsed JSON configuration
    (probably from ``NeckbeardLoader``) and creates an expanded configuration
    for each individual node in an environment. It handles:
        * Validating configuration for required options and internal consistency
        * Allows addons to validate their specific slice of configuration
        * Generating and properly scoping the template context required for
          expanding individual configuration options. eg.
            * environment.constants
            * environment.secrets
            * seed_environment.constants
            * seed_environment.secrets
            * node
            * seed_node
        * Determining the current scaling state for each `scaling_group` to
          determine how many nodes should exist.
        * And finally, it uses the scaling state, configuration, and context to
          generate an individual configuration for each node that should exist.
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

    def expand_configurations(self):
        pass

    def dump_node_configuration(self, output_directory):
        pass
