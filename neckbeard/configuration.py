import errno
import jinja2
import json
import logging
import os
import shutil

from collections import Mapping
from copy import deepcopy

from neckbeard.loader import NeckbeardLoader
from neckbeard.scaling import MinScalingBackend  # TODO: Don't hardcode this

logger = logging.getLogger('configuration')


class CircularSeedEnvironmentError(Exception):
    pass


class InfiniteEmptyStringDict(object):
    """
    An infinitely-nested dictionary where all individual values evaluate to ""
    when converted to a string.
    """
    def __str__(self):
        return ''

    def __unicode__(self):
        return ''

    def __len__(self):
        return 0

    def __getitem__(self, key):
        return InfiniteEmptyStringDict()

    def __contains__(self, key):
        return True

    def get(self, key, default=None):
        return self[key]


def mkdir_p(path):
    """
    Borrowed from: http://stackoverflow.com/a/600612/386925
    """
    try:
        os.makedirs(path)
    except OSError as exc:  # Python >2.5
        if exc.errno != errno.EEXIST or not os.path.isdir(path):
            raise


def evaluate_configuration_templates(configuration, context, debug_trace=''):
    """
    For the given `configuration` (a nested dictionary), walk the dictionary,
    evaluating any string values for Jinja2 template usage and walking any maps
    (dictionary-ish things) or lists to find any strings that need template
    expansion. The result is a dictionary with the same structure as the
    `configuration`, but with any Jinja2 template syntax fully rendered.

    Note: This function is recursive, but users of the function probably
    shouldn't attempt to take advantage of that fact.

    `context` is the template context which Jinja2 will use for evaluation.

    `debug_trace` is a dot-separated list to track how a key is nested for
    template evaluation (eg. 'neckbeard_meta.resource_tracker.path') so
    that error messages about template problems can point users to the exact
    place in their `configuration` where the error occurred. The recursive
    calls build this up.
    """
    if configuration is None:
        return None
    if isinstance(configuration, basestring):
        # TODO: Add validation here to catch the exception for
        # undefined
        env = jinja2.Environment(undefined=jinja2.StrictUndefined)
        template = env.from_string(configuration)
        try:
            return template.render(context)
        except jinja2.UndefinedError:
            logger.warning(
                "Error evaluating the template for: %s",
                debug_trace,
            )
            logger.warning("Template: %s", configuration)
            logger.warning("Context didn't contain a referenced variable")
            raise
        except jinja2.TemplateSyntaxError:
            logger.warning(
                "Jinja2 syntax error in the configuration template: %s",
                debug_trace,
            )
            logger.warning("Template: %s", configuration)
            raise

    constant_types = [bool, int, float]
    # These types can't have any strings nested inside of them, so we can just
    # use their current value directly
    for constant_type in constant_types:
        if isinstance(configuration, constant_type):
            return configuration

    evaluated_config = deepcopy(configuration)
    # Everything else is either a dictionary-like `Mapping` or an iterable,
    # either of which could contain strings that need template evaluation.
    # Recursively evaluate their children/members.
    if isinstance(configuration, Mapping):
        for key, value in configuration.iteritems():
            evaluated_config[key] = evaluate_configuration_templates(
                configuration=value,
                context=context,
                debug_trace="%s.%s" % (debug_trace, key),
            )
    else:
        for index, item in enumerate(configuration):
            evaluated_config[index] = evaluate_configuration_templates(
                configuration=item,
                context=context,
                debug_trace="%s.%s" % (debug_trace, index),
            )

    return evaluated_config


class ConfigurationManager(object):
    """
    ConfigurationManager accepts the already-parsed configuration
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

          The entire context is defined by `_get_config_context_for_resource`.
    """
    def __init__(
        self,
        scaling_backend,
        environments,
        constants=None,
        neckbeard_meta=None,
        secrets=None,
        secrets_tpl=None,
        node_templates=None,
    ):
        self.scaling_backend = scaling_backend
        self.environments = environments

        self.constants = constants or {}
        self.neckbeard_meta = neckbeard_meta or {}
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
            neckbeard_meta=raw_config.get('neckbeard_meta', {}),
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
        seed_environment_name = self.get_seed_environment_name(
            environment_name,
        )

        return self._get_environment_constants(seed_environment_name)

    def _get_seed_environment_secrets(self, environment_name):
        seed_environment_name = self.get_seed_environment_name(
            environment_name,
        )

        return self._get_environment_secrets(seed_environment_name)

    def get_seed_environment_name(
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
            seeds_seed = self.get_seed_environment_name(
                seed_environment_name,
                check_circular_reference=False,
            )
            if seeds_seed is not None:
                raise CircularSeedEnvironmentError()

        return seed_environment_name

    def _get_resource_context(
        self,
        environment_name,
        resource_type,
        resource_name,
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

        context['seed_environment_name'] = self.get_seed_environment_name(
            environment_name,
        )
        context['scaling_index'] = scaling_index

        return context

    def _get_seed_node_context(
        self,
        environment_name,
        resource_type,
        resource_name,
        scaling_index,
    ):
        environment = self.environments[environment_name]
        resource_types = environment['aws_nodes'][resource_type]
        node = resource_types[resource_name]

        seed_environment_name = self.get_seed_environment_name(
            environment_name,
        )
        if not seed_environment_name:
            # If there's no seed environment, you cant have a seed node
            return InfiniteEmptyStringDict()

        # No `seed` config means use the default. An empty or `None` config
        # means don't use a seed node
        if 'seed' in node and not node['seed']:
            return InfiniteEmptyStringDict()
        seed = node.get('seed', {})

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
            * environment.name
            * seed_environment.constants
            * seed_environment.secrets
            * seed_environment.name
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
        context['environment']['name'] = environment
        context['environment']['constants'] = self._get_environment_constants(
            environment,
        )
        context['environment']['secrets'] = self._get_environment_secrets(
            environment,
        )

        seed_env = context['seed_environment']
        seed_env_name = self.get_seed_environment_name(
            environment,
        )
        if not seed_env_name:
            seed_env['name'] = ''
            seed_env['constants'] = InfiniteEmptyStringDict()
            seed_env['secrets'] = InfiniteEmptyStringDict()
        else:
            seed_env['name'] = seed_env_name
            seed_env['constants'] = self._get_seed_environment_constants(
                environment,
            )
            seed_env['secrets'] = self._get_seed_environment_secrets(
                environment,
            )

        context['node'] = self._get_resource_context(
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

    def _get_neckbeard_config_context(self):
        """
        Get the context needed to evaluate Neckbeard meta configuration
        templates. This includes:

            * constants
            * secrets
        """
        context = {}
        context['constants'] = self.constants.get('neckbeard_meta', {})
        context['secrets'] = self.secrets.get('neckbeard_meta', {})

        return context

    def _apply_node_template(self, resource_type, resource_configuration):
        """
        If the given `resource_configuration` defines a `node_template_name`,
        then this function will find the matching `node_template` (based on the
        `resource_type`) and perform a deep merge.

        The end result is that any default values from the node template will
        be applied and a new `resource_configuration` will be returned with the
        defaults from its `node_template`.
        """

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

    def get_available_environments(self):
        """
        Return a list of environment names that are present within this
        configuration.
        """
        return self.environments.keys()

    def get_environment_config(self, environment_name):
        """
        Get the fully-evaluated configuration for the given `environment_name`.

        This process includes:
            * Applying any `Node Templates`
            * Using the `ScalingBackend` to determine how many of a resource
              will be available
            * Evaluating all template syntax with the appropriate context.

        The resulting configuration will be used by `neckbeard.actions` and
        consumed by Brain Wrinkles to actually act on resources.
        """
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
                    evaluated_conf = evaluate_configuration_templates(
                        configuration=expanded_configuration,
                        context=config_context,
                        debug_trace="%s.%s.%s" % (
                            environment_name,
                            resource_type,
                            resource_name,
                        ),
                    )
                    unique_id = evaluated_conf['unique_id']

                    # TODO: Detect duplicate unique ids
                    resource_conf[unique_id] = evaluated_conf

        return expanded_conf

    def get_neckbeard_meta_config(self):
        """
        Returns the Neckbeard "meta" configuration responsible for tweaking
        Neckbeard-specific functionality (like choice of ResourceTracker).

        This mostly just means evaluating the templates in configuration values
        with the appropriate secrets/constants.
        """
        config_context = self._get_neckbeard_config_context()

        evaluated_config = evaluate_configuration_templates(
            configuration=self.neckbeard_meta,
            context=config_context,
            debug_trace="neckbeard_meta",
        )

        # Remove the version. That's only for the Loader and
        # ConfigurationManager's use
        evaluated_config.pop(NeckbeardLoader.VERSION_OPTION)

        return evaluated_config

    def dump_environment_config(
        self, environment_name, output_directory,
    ):
        expanded_configuration = self.get_environment_config(
            environment_name,
        )

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
                    json.dump(resource_config, fp, indent=4)
