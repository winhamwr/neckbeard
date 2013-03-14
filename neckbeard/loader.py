
import json
import logging
import os
from copy import copy

logger = logging.getLogger('loader')

def all_json_files(directory):
    """
    Generator to iterate through all the JSON files in a directory.
    """
    for path, dirs, files in os.walk(directory):
        for f in files:
            if f.endswith('.json'):
                yield os.path.join(path, f)


class NeckbeardLoader(object):
    """
    The loader takes a directory of Neckbeard configuration files and spits out
    a Neckbeard instance with the gathered configuration.

    Along the way, it also does bare minimum validation, ensuring that:

        * We're not missing any required files
        * Everything is valid JSON
        * Everything is properly versioned with a `neckbeard_conf_version`
        * JSON properties that should agree with the directory structure
          actually do that (you can't put an `ec2` node_template in an `rds`
          directory).
    """
    VALIDATION_MESSAGES = {
        'invalid_configuration_directory': (
            "The configuration directory "
            "does not exist or is not accessible."
        ),
        'invalid_json': (
            "Invalid JSON. Check for trailing commas. "
            "Error: %(error)s"
        ),
        'missing_file': "File is required, but missing.",
        'missing_environment': (
            "You need at least one environment configuration, "
            "or what are we really doing here? "
            "I recommend starting with <%(file_path)s/staging.json>"
        ),
        'missing_option': (
            "The option '%(option_name)s' is required, but missing."
        ),
        'file_option_mismatch': (
            "The option '%(option_name)s' doesn't match its folder structure. "
            "Expected: '%(expected)s' But found: '%(actual)s'"
        ),
    }
    CONFIG_STRUCTURE = {
        "constants": None,
        "secrets": None,
        "secrets.tpl": None,
        "environments": {},
        "node_templates": {
            "ec2": {},
            "rds": {},
            "elb": {},
        },
    }
    ROOT_CONF_FILES = [
        'constants',
        'secrets',
        'secrets.tpl',
    ]
    VERSION_OPTION = 'neckbeard_conf_version'

    def __init__(self, configuration_directory):
        self.configuration_directory = configuration_directory
        # A dictionary of errors keyed based on the file to which they are
        # related. The error itself is a 2-tuple of the ErrorType plus a
        # message.
        self.validation_errors = {}
        self.raw_configuration = copy(self.CONFIG_STRUCTURE)

    def _add_validation_error(self, file_path, error_type, extra_context=None):
        if not file_path in self.validation_errors:
            self.validation_errors[file_path] = {}

        if not error_type in self.validation_errors[file_path]:
            self.validation_errors[file_path][error_type] = []

        context = {'file_path': file_path}
        if extra_context:
            context.update(extra_context)

        error_message = self.VALIDATION_MESSAGES[error_type] % context
        logger.debug("Validation Error: %s", error_message)

        self.validation_errors[file_path][error_type].append(error_message)

    def _add_path_relative_validation_error(
        self, relative_path, error_type, extra_context=None):

        file_path = os.path.join(self.configuration_directory, relative_path)
        self._add_validation_error(file_path, error_type, extra_context)

    def print_validation_errors(self):
        for file_path, error_types in self.validation_errors.items():
            logger.warning("%s errors:", file_path)
            for error_type, errors in error_types.items():
                for error in errors:
                    logger.warning("    %s", error)

    def _get_json_from_file(self, file_path):
        try:
            with open(file_path, 'r') as fp:
                try:
                    return json.load(fp)
                except ValueError as e:
                    logger.debug("Error parsing JSON file: %s", file_path)
                    logger.debug("%s", e)
                    self._add_validation_error(
                        file_path,
                        'invalid_json',
                        extra_context={'error': e},
                    )
                    return {}
        except IOError as e:
            logger.debug("Error opening JSON file: %s", file_path)
            logger.debug("%s", e)
            self._add_validation_error(
                file_path,
                'missing_file',
            )
            return {}

    def _get_name_from_json_path(self, file_path):
        """
        Given a file path to a json config file, get the file's path-roomed and
        .json-removed name. For environment files, this is the environment
        name. For node_templates, the template name, etc.
        """
        _, tail = os.path.split(file_path)
        name, _ = tail.rsplit('.json', 1)

        return name

    def _load_root_configuration_files(self, configuration_directory):
        root_configs = {}
        for conf_file in self.ROOT_CONF_FILES:
            fp = os.path.join(configuration_directory, '%s.json' % conf_file)
            root_configs[conf_file] = self._get_json_from_file(fp)

        return root_configs

    def _load_environment_files(self, configuration_directory):
        environment_dir = os.path.join(configuration_directory, 'environments')
        configs = {}

        for environment_config_fp in all_json_files(environment_dir):
            name = self._get_name_from_json_path(environment_config_fp)
            configs[name] = self._get_json_from_file(environment_config_fp)

        if len(configs) == 0:
            # There were no environment files. That's a problem
            self._add_validation_error(
                environment_dir,
                'missing_environment',
            )

        return configs

    def _load_node_template_files(self, configuration_directory):
        node_templates_dir = os.path.join(configuration_directory, 'node_templates')
        configs = copy(self.CONFIG_STRUCTURE['node_templates'])

        # If there aren't any node_templates, no sweat
        if not os.path.exists(node_templates_dir):
            logger.debug("No node_templates configuration found")
            return configs

        # Gather up node_templates for the various AWS node types
        aws_types = configs.keys()
        for aws_type in aws_types:
            node_type_dir = os.path.join(node_templates_dir, aws_type)
            if not os.path.exists(node_type_dir):
                logger.debug(
                    "No %s node_templates configurations found",
                    aws_type,
                )
                continue

            for node_config_fp in all_json_files(node_type_dir):
                name = self._get_name_from_json_path(node_config_fp)
                configs[aws_type][name] = self._get_json_from_file(
                    node_config_fp,
                )

        return configs

    def _load_configuration_files(self, configuration_directory):
        if not os.path.exists(configuration_directory):
            self._add_validation_error(
                configuration_directory,
                'invalid_configuration_directory',
            )
            return {}

        config = self._load_root_configuration_files(configuration_directory)

        environments = self._load_environment_files(configuration_directory)
        config['environments'] = environments

        node_templates = self._load_node_template_files(configuration_directory)
        config['node_templates'] = node_templates

        return config

    def _validate_option_agrees(
        self, relative_path, name, expected_value, config, required=True):

        actual_value = config.get(name)
        if actual_value is None:
            if required:
                self._add_path_relative_validation_error(
                    relative_path,
                    'missing_option',
                    extra_context={'option_name': name},
                )
                return
        elif actual_value != expected_value:
            self._add_path_relative_validation_error(
                relative_path,
                'file_option_mismatch',
                extra_context={
                    'option_name': name,
                    'expected': expected_value,
                    'actual': actual_value,
                },
            )

    def _validate_node_template_agreement(self, raw_configuration):
        """
        Ensure that the `node_aws_type` and `node_template_name` for each
        `node_template` configuration actually agrees with the folder structure
        in which it was contained.

        A `node_templates/ec2/foo.json` template file should not say it's an
        `rds` node called `bar`.
        """
        raw_node_template_config = raw_configuration['node_templates']

        for aws_type, node_templates in raw_node_template_config.items():
            for node_template_name, config in node_templates.items():
                # Check for existence and folder structure mismatch
                relative_path = 'node_templates/%s/%s.json' % (
                    aws_type,
                    node_template_name,
                )
                self._validate_option_agrees(
                    relative_path,
                    'node_aws_type',
                    aws_type,
                    config,
                )
                self._validate_option_agrees(
                    relative_path,
                    'node_template_name',
                    node_template_name,
                    config,
                )

    def _validate_environment_name_agreement(self, raw_configuration):
        environments_config = raw_configuration['environments']

        for environment_name, config in environments_config.items():
            # Check for existence and folder structure mismatch
            relative_path = 'environments/%s.json' % environment_name
            self._validate_option_agrees(
                relative_path,
                'name',
                environment_name,
                config,
            )

    def _validate_neckbeard_conf_version(self, raw_configuration):

        # Check all of the root configuration files
        for root_conf in self.ROOT_CONF_FILES:
            if not raw_configuration[root_conf].get(self.VERSION_OPTION):
                relative_path = '%s.json' % root_conf
                self._add_path_relative_validation_error(
                    relative_path,
                    'missing_option',
                    extra_context={
                        'option_name': self.VERSION_OPTION,
                    },
                )

        # Check all of the environment configs
        for name, config in raw_configuration['environments'].items():
            if not config.get(self.VERSION_OPTION):
                relative_path = 'environments/%s.json' % name
                self._add_path_relative_validation_error(
                    relative_path,
                    'missing_option',
                    extra_context={
                        'option_name': self.VERSION_OPTION,
                    },
                )


        # Check all of the node_templates
        all_node_templates = raw_configuration.get('node_templates', {})
        for aws_type, node_templates in all_node_templates.items():
            for node_template_name, config in node_templates.items():
                if not config.get(self.VERSION_OPTION):
                    relative_path = 'node_templates/%s/%s.json' % (
                        aws_type,
                        node_template_name,
                    )
                    self._add_path_relative_validation_error(
                        relative_path,
                        'missing_option',
                        extra_context={
                            'option_name': self.VERSION_OPTION,
                        },
                    )

    def _validate_configuration(self):
        self.validation_errors = {}
        self.raw_configuration = self._load_configuration_files(
            self.configuration_directory,
        )
        if len(self.validation_errors) > 0:
            # If there are errors loading/parsing the files, don't attempt
            # further validation
            return

        self._validate_neckbeard_conf_version(self.raw_configuration)
        if len(self.validation_errors) > 0:
            # If we can't determine the configuration version of the files, we
            # can't rely on any other validation
            return

        self._validate_node_template_agreement(self.raw_configuration)
        self._validate_environment_name_agreement(self.raw_configuration)

    def configuration_is_valid(self):
        self._validate_configuration()

        if len(self.validation_errors) > 0:
            return False

        return True

    def get_neckbeard_configuration(self):
        if not self.configuration_is_valid():
            self.print_validation_errors()
            return None

        pass




