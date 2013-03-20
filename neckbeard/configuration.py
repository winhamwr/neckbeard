import errno
import jinja2
import json
import logging
import os
import shutil

from collections import Mapping
from copy import deepcopy

from neckbeard.scaling import MinScalingBackend  # TODO: Don't hardcode this

logger = logging.getLogger('configuration')


class CircularSeedEnvironmentError(Exception):
    pass


def mkdir_p(path):
    """
    Borrowed from: http://stackoverflow.com/a/600612/386925
    """
    try:
        os.makedirs(path)
    except OSError as exc:  # Python >2.5
        if exc.errno != errno.EEXIST or not os.path.isdir(path):
            raise


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
    def __init__(
        self,
        scaling_backend,
        environments,
        constants=None,
        secrets=None,
        secrets_tpl=None,
        node_templates=None,
    ):
        self.scaling_backend = scaling_backend
        self.environments = environments

        self.constants = constants or {}
        self.secrets = secrets or {}
        self.secrets_tpl = secrets_tpl or {}
        self.node_templates = node_templates or {}

        self._expanded_configuration = {}

    @classmethod
    def from_loader(cls, loader):
        """
        Create a new `ConfigurationManager` from an existing
        ``NeckbeardLoader``.
        """
        raw_config = loader.raw_configuration
        configuration = cls(
            environments=raw_config['environments'],
            scaling_backend=MinScalingBackend(),
            constants=raw_config.get('constants', {}),
            secrets=raw_config.get('secrets', {}),
            secrets_tpl=raw_config.get('secrets_tpl', {}),
            node_templates=raw_config.get('node_templates', {}),
        )

        return configuration

    def is_valid(self):
        # TODO: Actually do some like, you know, validation
        return True

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
        self,
        environment_name,
        check_circular_reference=True,
    ):
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
                "seed_environment %s does not exist" % seed_environment_name)
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

    def _get_node_context(
        self, environment_name, resource_type, resource_name,
        scaling_index,
    ):
        """
        Returns a dictionary with the following values for the given node.

          * environment_name
          * seed_environment_name
          * resource_type
          * name
          * scaling_index
        """
        context = {
            'environment_name': environment_name,
            'resource_type': resource_type,
            'name': resource_name,
        }

        context['seed_environment_name'] = self._get_seed_environment_name(
            environment_name,
        )
        context['scaling_index'] = scaling_index

        return context

    def _get_seed_node_context(
        self, environment_name, resource_type, resource_name,
        scaling_index,
    ):

        environment = self.environments[environment_name]
        resource_types = environment['aws_nodes'][resource_type]
        node = resource_types[resource_name]

        seed_environment_name = self._get_seed_environment_name(
            environment_name,
        )

        seed = node.get('seed', None)
        if not seed:
            return {}

        context = {}
        context['resource_type'] = resource_type
        context['name'] = seed.get('name', resource_name)
        context['scaling_index'] = seed.get(
            'scaling_index',
            scaling_index,
        )
        context['environment_name'] = seed_environment_name
        context['seed_environment_name'] = None

        return context

    def _get_config_context_for_resource(
        self, environment, resource_type, name, scaling_index=0,
    ):
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
              * scaling_index
            * seed_node
              * environment_name
              * seed_environment_name
              * resource_type
              * name
              * scaling_index
        """
        context = {
            'environment': {},
            'seed_environment': {},
        }
        context['environment']['constants'] = self._get_environment_constants(
            environment,
        )
        context['environment']['secrets'] = self._get_environment_secrets(
            environment,
        )
        seed_env = context['seed_environment']
        seed_env['constants'] = self._get_seed_environment_constants(
            environment,
        )
        seed_env['secrets'] = self._get_seed_environment_secrets(
            environment,
        )

        context['node'] = self._get_node_context(
            environment,
            resource_type,
            name,
            scaling_index,
        )
        context['seed_node'] = self._get_seed_node_context(
            environment,
            resource_type,
            name,
            scaling_index,
        )
        return context

    def _apply_node_template(self, resource_type, resource_configuration):

        def deep_merge(base, overrides):
            if not isinstance(overrides, Mapping):
                return overrides
            result = deepcopy(base)
            for key, value in overrides.iteritems():
                if key in result and isinstance(result[key], Mapping):
                    result[key] = deep_merge(result[key], value)
                else:
                    result[key] = deepcopy(value)
            return result

        node_template_name = resource_configuration.get(
            'node_template_name',
        )
        if not node_template_name:
            return resource_configuration

        # TODO: Do validation here when the template doesn't exist
        node_templates = self.node_templates[resource_type]
        node_template = node_templates[node_template_name]

        return deep_merge(
            node_template['defaults'],
            resource_configuration,
        )

    def _evaluate_configuration(self, config_context, resource_configuration):
        def evaluate_templates(config, context):
            if isinstance(config, basestring):
                # TODO: Add validation here to catch the exception for
                # undefined
                env = jinja2.Environment(undefined=jinja2.StrictUndefined)
                template = env.from_string(config)
                return template.render(context)
            constant_types = [bool, int, float]
            for constant_type in constant_types:
                if isinstance(config, constant_type):
                    return config

            result = deepcopy(config)
            if isinstance(config, Mapping):
                for key, value in config.iteritems():
                    result[key] = evaluate_templates(value, context)
            else:
                for index, item in config.enumerate():
                    result[key] = evaluate_templates(item, context)

            return result

        evaluated_template = evaluate_templates(
            resource_configuration,
            config_context,
        )
        return (evaluated_template['unique_id'], evaluated_template)

    def expand_configurations(self, environment_name):
        if environment_name in self._expanded_configuration:
            return self._expanded_configuration[environment_name]

        environment = self.environments[environment_name]
        expanded_conf = {}

        for resource_type, resources in environment['aws_nodes'].items():
            expanded_conf[resource_type] = {}
            for resource_name, configuration in resources.items():
                resource_conf = expanded_conf[resource_type]

                # Apply the `node_template`, if used
                expanded_configuration = self._apply_node_template(
                    resource_type,
                    configuration,
                )
                for index in self.scaling_backend.get_indexes_for_resource(
                    environment_name,
                    resource_type,
                    resource_name,
                    expanded_configuration,
                ):
                    logger.debug(
                        "Expanding context for the %dth %s %s resource",
                        index,
                        resource_name,
                        resource_type,
                    )
                    config_context = self._get_config_context_for_resource(
                        environment_name,
                        resource_type,
                        resource_name,
                        scaling_index=index,
                    )
                    result = self._evaluate_configuration(
                        config_context,
                        expanded_configuration,
                    )
                    unique_id, evaluated_resource_conf = result

                    # TODO: Detect duplicate unique ids
                    resource_conf[unique_id] = evaluated_resource_conf

        return expanded_conf

    def dump_environment_configuration(
        self, environment_name, output_directory,
    ):
        expanded_configuration = self.expand_configurations(environment_name)

        if os.path.exists(output_directory):
            shutil.rmtree(output_directory)

        mkdir_p(output_directory)

        for resource_type, resources in expanded_configuration.items():
            resource_type_dir = os.path.join(output_directory, resource_type)
            mkdir_p(resource_type_dir)
            for unique_id, resource_config in resources.items():
                resource_file = os.path.join(
                    resource_type_dir,
                    '%s.json' % unique_id,
                )

                with open(resource_file, 'w') as fp:
                    json.dump(resource_config, fp)


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
