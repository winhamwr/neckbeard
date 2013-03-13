
import json
import logging
import os
from copy import copy

logger = logging.getLogger('loader')
logging.basicConfig()
logger.setLevel(logging.DEBUG)

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
            "The configuration directory %(file_path)s "
            "does not exist or is not accessible."
        ),
        'invalid_json': (
            "%(file_path)s has invalid JSON. Check for trailing commas. "
            "Error: %(error)s"
        ),
        'missing_file': "%(file_path)s is required, but missing.",
        'missing_environment': (
            "You need at least one environment configuration, "
            "or what are we really doing here? "
            "I recommend starting with <%(file_path)s/staging.json>"
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

    def print_validation_errors(self):
        for file_path, error_types in self.validation_errors.items():
            logger.warning("%s errors:", file_path)
            for error_type, errors in error_types.items():
                logger.warning("  %s:", file_path)
                for error in errors:
                    logger.warning("    %s:", error)
                logger.warning("")
            logger.warning("")

    def _get_json_from_file(self, file_path):
        try:
            with open(file_path, 'r') as fp:
                try:
                    return json.load(fp)
                except ValueError as e:
                    logger.warning("Error parsing JSON file: %s", file_path)
                    logger.warning("%s", e)
                    self._add_validation_error(
                        file_path,
                        'invalid_json',
                        extra_context={'error': e},
                    )
                    return {}
        except IOError as e:
            logger.warning("Error opening JSON file: %s", file_path)
            logger.warning("%s", e)
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
        root_conf_files = [
            'constants',
            'secrets',
            'secrets.tpl',
        ]
        for conf_file in root_conf_files:
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
        aws_types = ['ec2', 'rds', 'elb']
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

    def _validate_configuration(self):
        self.validation_errors = {}
        self.raw_configuration = self._load_configuration_files(
            self.configuration_directory,
        )

    def configuration_is_valid(self):
        self._validate_configuration()

        if len(self.validation_errors) > 0:
            return False

        return True

    def get_configured_neckbeard(self):
        if not self.configuration_is_valid:
            self.print_validation_errors()
            return None

        pass




