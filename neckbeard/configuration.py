

class CircularSeedEnvironmentError(Exception):
    pass


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
                 constants, secrets, secrets_tpl, environments, node_templates,
                 scaling_manager):
        self.constants = constants
        self.secrets = secrets
        self.secrets_tpl = secrets_tpl
        self.environments = environments
        self.node_templates = node_templates
        self.scaling_manager = scaling_manager

    def is_valid(self):
        pass

    def print_validation_errors(self):
        pass

    def _get_environment_constants(self, environment_name):
        environments = self.constants.get('environments', {})
        return environments.get(environment_name, {})

    def _get_environment_secrets(self, environment_name):
        environments = self.secrets.get('environments', {})
        return environments.get(environment_name, {})

    def _get_seed_environment_constants(self, environment_name):
        seed_environment_name = self._get_seed_environment_name(
            environment_name,
        )

        return self._get_environment_constants(seed_environment_name)

    def _get_seed_environment_secrets(self, environment_name):
        seed_environment_name = self._get_seed_environment_name(
            environment_name,
        )

        return self._get_environment_secrets(seed_environment_name)

    def _get_seed_environment_name(
        self, environment_name, check_circular_reference=True):
        """
        Get the `seed_environment` name for the given environment.
        """
        environment = self.environments[environment_name]
        seed_environment_name = environment.get(
            'seed_environment_name',
            None,
        )
        if seed_environment_name is None:
            return None
        # Now let's make sure that this `seed_environment` actually exists
        if seed_environment_name not in self.environments:
            # TODO: This should actually be caught by requiring validation
            # before doing any of this stuff and this should be a type of
            # validation error.
            raise Exception(
                "seed_environment %s does not exist" % seed_environment)
        # TODO: This should actually be caught by requiring validation
        # before doing any of this stuff and this should be a type of
        # validation error.
        if check_circular_reference:
            seeds_seed = self._get_seed_environment_name(
                seed_environment_name,
                check_circular_reference=False,
            )
            if seeds_seed is not None:
                raise CircularSeedEnvironmentError()

        return seed_environment_name

    def _get_node_context(self, environment_name, resource_type, resource_name):
        """
        Returns a dictionary with the following values for the given node.

          * environment_name
          * seed_environment_name
          * resource_type
          * name
          * index_for_scaling_group
        """
        context = {
            'environment_name': environment_name,
            'resource_type': resource_type,
            'name': resource_name,
        }

        context['seed_environment_name'] = self._get_seed_environment_name(
            environment_name,
        )
        index = self.scaling_manager.get_index_for_resource(
            environment_name,
            resource_type,
            resource_name,
        )
        context['index_for_scaling_group'] = index

        return context

    def _get_seed_node_context(self, node_context):
        environment = self.environments[node_context['environment_name']]
        resource_types = environment['aws_nodes'][node_context['resource_type']]
        node = resource_types[node_context['name']]

        seed_environment_name = self._get_seed_environment_name(
            node_context['environment_name'],
        )

        seed = node.get('seed', None)
        if seed is None:
            return {}

        context = {}
        context['resource_type'] = node_context['resource_type']
        context['name'] = seed.get('name', node_context['name'])
        context['index_for_scaling_group'] =  seed.get(
            'index_for_scaling_group',
            node_context['index_for_scaling_group'],
        )
        context['environment_name'] = seed_environment_name
        context['seed_environment_name'] = None

        return context

    def get_config_context_for_resource(
        self, environment, resource_type, name, index=0):
        """
        For a particular index of a particular resource, get the template
        context used for generating the configuration. This includes:
            * environment.constants
            * environment.secrets
            * seed_environment.constants
            * seed_environment.secrets
            * node
              * environment_name
              * seed_environment_name
              * resource_type
              * name
              * index_for_scaling_group
            * seed_node
              * environment_name
              * seed_environment_name
              * resource_type
              * name
              * index_for_scaling_group
        """
        return {}

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

