
import unittest
from os import path

from neckbeard.loader import NeckbeardLoader

FIXTURE_CONFIGS_DIR = path.abspath(
    path.join(path.dirname(__file__), 'fixture_configs'),
)


class FileLoadingHelper(unittest.TestCase):
    def _get_loader_for_fixture(self, fixture_name):
        configuration_directory = path.join(FIXTURE_CONFIGS_DIR, fixture_name)

        return NeckbeardLoader(configuration_directory)

    def _get_validation_errors(self, loader, config_file, error_type=None):
        """
        `config_file` is the file's path relative to the root configuration
        directory.
        """
        full_fp = path.join(loader.configuration_directory, config_file)
        if full_fp not in loader.validation_errors:
            return []

        if error_type is None:
            return loader.validation_errors[full_fp]

        if error_type not in loader.validation_errors[full_fp]:
            return []

        return loader.validation_errors[full_fp][error_type]


class TestFileLoading(FileLoadingHelper):

    def test_all_files_loaded(self):
        # Ensure that a load on a minimally-valid configuration results in the
        # expected JSON configuration objects
        loader = self._get_loader_for_fixture('minimal')

        self.assertTrue(loader.configuration_is_valid())

        # We should have loaded both environments
        environments = ['beta', 'production']
        for environment_name in environments:
            self.assertTrue(
                environment_name in loader.raw_configuration['environments'],
            )
        self.assertEqual(
            len(loader.raw_configuration['environments']),
            len(environments),
        )

        # Should have loaded all of the node_templates
        expected_node_templates = {
            "ec2": ['backend', 'web'],
            "rds": ['master', 'slave'],
            "elb": ['web', 'api'],
        }
        node_templates = loader.raw_configuration['node_templates']
        for aws_type, expected_templates in expected_node_templates.items():
            node_templates_for_type = node_templates[aws_type]
            for expected_node_template in expected_templates:
                self.assertTrue(
                    expected_node_template in node_templates_for_type,
                )
            self.assertEqual(
                len(node_templates_for_type),
                len(expected_templates),
            )

    def test_invalid_path(self):
        # We give a nice error if the `configuration_directory` doesn't exist
        # or we can't access it
        loader = self._get_loader_for_fixture('does_not_exist')

        self.assertFalse(loader.configuration_is_valid())

        self.assertEqual(len(loader.validation_errors), 1)

    def test_missing_files(self):
        # We should ensure that all of the required files are present
        loader = self._get_loader_for_fixture('empty')

        self.assertFalse(loader.configuration_is_valid())

        validation_errors = self._get_validation_errors(
            loader,
            'constants',
            'missing_file',
        )
        self.assertEqual(len(validation_errors), 1)
        validation_errors = self._get_validation_errors(
            loader,
            'neckbeard_meta',
            'missing_file',
        )
        self.assertEqual(len(validation_errors), 1)
        validation_errors = self._get_validation_errors(
            loader,
            'secrets',
            'missing_file',
        )
        self.assertEqual(len(validation_errors), 1)
        validation_errors = self._get_validation_errors(
            loader,
            'secrets.tpl',
            'missing_file',
        )
        self.assertEqual(len(validation_errors), 1)
        validation_errors = self._get_validation_errors(
            loader,
            'environments',
            'missing_environment',
        )
        self.assertEqual(len(validation_errors), 1)

    def test_json_and_yaml_with_same_name_add_duplicate_config_error(self):
        loader = self._get_loader_for_fixture('duplicate_errors')

        self.assertFalse(loader.configuration_is_valid())

        validation_errors = self._get_validation_errors(
            loader,
            'environments/beta',
            'duplicate_config',
        )
        self.assertEqual(len(validation_errors), 2)


class TestJsonLoading(FileLoadingHelper):
    def test_json_to_dict(self):
        # Ensure that all of the JSON files have been converted to python
        # dictionaries
        loader = self._get_loader_for_fixture('minimal')
        self.assertTrue(loader.configuration_is_valid())

        # Ensure things are dictionaries by treating them as such. One from
        # each type of file
        self.assertEqual(
            loader.raw_configuration['constants'].get(
                NeckbeardLoader.VERSION_OPTION,
            ),
            '0.1',
        )
        self.assertEqual(
            loader.raw_configuration['neckbeard_meta'].get(
                NeckbeardLoader.VERSION_OPTION,
            ),
            '0.1',
        )
        self.assertEqual(
            loader.raw_configuration['secrets'].get(
                NeckbeardLoader.VERSION_OPTION,
            ),
            '0.1',
        )
        self.assertEqual(
            loader.raw_configuration['secrets.tpl'].get(
                NeckbeardLoader.VERSION_OPTION,
            ),
            '0.1',
        )
        environments = loader.raw_configuration['environments']
        self.assertEqual(
            environments['production'].get('name'),
            'production',
        )
        node_templates = loader.raw_configuration['node_templates']
        self.assertEqual(
            node_templates['ec2']['web'].get('node_template_name'),
            'web',
        )
        self.assertEqual(
            node_templates['rds']['master'].get('node_template_name'),
            'master',
        )
        self.assertEqual(
            node_templates['elb']['api'].get('node_template_name'),
            'api',
        )

    def test_invalid_json(self):
        # If a file is invalid JSON, we should display that as a validation
        # error and bail out early
        loader = self._get_loader_for_fixture('validation_errors')

        self.assertFalse(loader.configuration_is_valid())

        validation_errors = self._get_validation_errors(
            loader,
            'constants.json',
            'invalid_json',
        )
        self.assertEqual(len(validation_errors), 1)


class TestYamlLoading(FileLoadingHelper):
    def test_yaml_to_dict(self):
        # Ensure that all of the YAML files have been converted to python
        # dictionaries
        loader = self._get_loader_for_fixture('minimal_yaml')

        self.assertTrue(loader.configuration_is_valid())

        # Ensure things are dictionaries by treating them as such. One from
        # each type of file
        self.assertEqual(
            loader.raw_configuration['constants'].get(
                NeckbeardLoader.VERSION_OPTION,
            ),
            '0.1',
        )
        self.assertEqual(
            loader.raw_configuration['neckbeard_meta'].get(
                NeckbeardLoader.VERSION_OPTION,
            ),
            '0.1',
        )
        self.assertEqual(
            loader.raw_configuration['secrets'].get(
                NeckbeardLoader.VERSION_OPTION,
            ),
            '0.1',
        )
        self.assertEqual(
            loader.raw_configuration['secrets.tpl'].get(
                NeckbeardLoader.VERSION_OPTION,
            ),
            '0.1',
        )
        environments = loader.raw_configuration['environments']
        self.assertEqual(
            environments['production'].get('name'),
            'production',
        )
        node_templates = loader.raw_configuration['node_templates']
        self.assertEqual(
            node_templates['ec2']['web'].get('node_template_name'),
            'web',
        )
        self.assertEqual(
            node_templates['rds']['master'].get('node_template_name'),
            'master',
        )
        self.assertEqual(
            node_templates['elb']['api'].get('node_template_name'),
            'api',
        )

    def test_invalid_yaml(self):
        # If a file is invalid YAML, we should display that as a validation
        # error and bail out early
        loader = self._get_loader_for_fixture('validation_errors_yaml')

        self.assertFalse(loader.configuration_is_valid())

        validation_errors = self._get_validation_errors(
            loader,
            'constants.yaml',
            'invalid_yaml',
        )
        self.assertEqual(len(validation_errors), 1)


class TestValidation(FileLoadingHelper):

    def test_node_aws_type_mismatch(self):
        # We should ensure that `node_aws_type` matches the directory where the
        # node_template JSON file lives
        loader = self._get_loader_for_fixture('minimal')
        loader.validation_errors = {}

        raw_configuration = {
            'node_templates': {
                'ec2': {
                    'wrong_type': {
                        'node_template_name': 'wrong_type',
                        'node_aws_type': 'mismatch',
                    },
                    'both_wrong': {
                        'node_template_name': 'mismatch',
                        'node_aws_type': 'mismatch',
                    },
                    'correct': {
                        'node_template_name': 'correct',
                        'node_aws_type': 'ec2',
                    },
                },
                'foo': {
                    'correct': {
                        'node_template_name': 'correct',
                        'node_aws_type': 'foo',
                    },
                    'both_wrong': {
                        'node_template_name': 'mismatch',
                        'node_aws_type': 'mismatch',
                    },
                },
            },
        }

        loader._validate_node_template_agreement(raw_configuration)

        validation_errors = self._get_validation_errors(
            loader,
            'node_templates/ec2/wrong_type.json',
            'file_option_mismatch',
        )
        self.assertEqual(len(validation_errors), 1)

        validation_errors = self._get_validation_errors(
            loader,
            'node_templates/ec2/both_wrong.json',
            'file_option_mismatch',
        )
        self.assertEqual(len(validation_errors), 2)

        validation_errors = self._get_validation_errors(
            loader,
            'node_templates/ec2/correct.json',
            'file_option_mismatch',
        )
        self.assertEqual(len(validation_errors), 0)

        validation_errors = self._get_validation_errors(
            loader,
            'node_templates/foo/both_wrong.json',
            'file_option_mismatch',
        )
        self.assertEqual(len(validation_errors), 2)

        validation_errors = self._get_validation_errors(
            loader,
            'node_templates/foo/correct.json',
            'file_option_mismatch',
        )
        self.assertEqual(len(validation_errors), 0)

    def test_node_template_name_mismatch(self):
        # We should ensure that `node_template_name` matches the filename
        # (minus JSON) where the node_template JSON file lives
        loader = self._get_loader_for_fixture('minimal')
        loader.validation_errors = {}

        raw_configuration = {
            'node_templates': {
                'ec2': {
                    'wrong_name': {
                        'node_template_name': 'mismatch',
                        'node_aws_type': 'ec2',
                    },
                    'both_wrong': {
                        'node_template_name': 'mismatch',
                        'node_aws_type': 'mismatch',
                    },
                    'correct': {
                        'node_template_name': 'correct',
                        'node_aws_type': 'ec2',
                    },
                },
                'foo': {
                    'correct': {
                        'node_template_name': 'correct',
                        'node_aws_type': 'foo',
                    },
                    'both_wrong': {
                        'node_template_name': 'mismatch',
                        'node_aws_type': 'mismatch',
                    },
                },
            },
        }

        loader._validate_node_template_agreement(raw_configuration)

        validation_errors = self._get_validation_errors(
            loader,
            'node_templates/ec2/wrong_name.json',
            'file_option_mismatch',
        )
        self.assertEqual(len(validation_errors), 1)

        validation_errors = self._get_validation_errors(
            loader,
            'node_templates/ec2/both_wrong.json',
            'file_option_mismatch',
        )
        self.assertEqual(len(validation_errors), 2)

        validation_errors = self._get_validation_errors(
            loader,
            'node_templates/ec2/correct.json',
        )
        self.assertEqual(len(validation_errors), 0)

        validation_errors = self._get_validation_errors(
            loader,
            'node_templates/foo/both_wrong.json',
            'file_option_mismatch',
        )
        self.assertEqual(len(validation_errors), 2)

        validation_errors = self._get_validation_errors(
            loader,
            'node_templates/foo/correct.json',
            'file_option_mismatch',
        )
        self.assertEqual(len(validation_errors), 0)

    def test_node_template_required_options(self):
        loader = self._get_loader_for_fixture('minimal')
        loader.validation_errors = {}

        raw_configuration = {
            'node_templates': {
                'ec2': {
                    'missing_type': {
                        'node_template_name': 'missing_type',
                    },
                    'missing_name': {
                        'node_aws_type': 'ec2',
                    },
                    'missing': {},
                    'correct': {
                        'node_template_name': 'correct',
                        'node_aws_type': 'ec2',
                    },
                },
                'foo': {
                    'correct': {
                        'node_template_name': 'correct',
                        'node_aws_type': 'foo',
                    },
                    'missing': {},
                },
            },
        }
        loader._validate_node_template_agreement(raw_configuration)

        validation_errors = self._get_validation_errors(
            loader,
            'node_templates/ec2/missing_type.json',
            'missing_option',
        )
        self.assertEqual(len(validation_errors), 1)

        validation_errors = self._get_validation_errors(
            loader,
            'node_templates/ec2/missing_name.json',
            'missing_option',
        )
        self.assertEqual(len(validation_errors), 1)

        validation_errors = self._get_validation_errors(
            loader,
            'node_templates/ec2/missing.json',
            'missing_option',
        )
        self.assertEqual(len(validation_errors), 2)

        validation_errors = self._get_validation_errors(
            loader,
            'node_templates/ec2/correct.json',
        )
        self.assertEqual(len(validation_errors), 0)

        validation_errors = self._get_validation_errors(
            loader,
            'node_templates/foo/missing.json',
            'missing_option',
        )
        self.assertEqual(len(validation_errors), 2)

        validation_errors = self._get_validation_errors(
            loader,
            'node_templates/foo/correct.json',
        )
        self.assertEqual(len(validation_errors), 0)

    def test_environment_name_mismatch(self):
        # We should ensure that, for environments, the `name` matches the
        # filename (minus JSON) where the JSON file lives
        loader = self._get_loader_for_fixture('minimal')
        loader.validation_errors = {}

        raw_configuration = {
            'environments': {
                'correct': {
                    'name': 'correct',
                },
                'mismatch': {
                    'name': 'wrong',
                },
                'missing': {},
            },
        }
        loader._validate_environment_name_agreement(raw_configuration)

        validation_errors = self._get_validation_errors(
            loader,
            'environments/correct.json',
        )
        self.assertEqual(len(validation_errors), 0)

        validation_errors = self._get_validation_errors(
            loader,
            'environments/mismatch.json',
            'file_option_mismatch',
        )
        self.assertEqual(len(validation_errors), 1)

        validation_errors = self._get_validation_errors(
            loader,
            'environments/missing.json',
            'missing_option',
        )
        self.assertEqual(len(validation_errors), 1)

    def test_neckbeard_conf_version_required(self):
        # All configs everywhere need a `neckbeard_conf_version`
        loader = self._get_loader_for_fixture('minimal')
        loader.validation_errors = {}

        raw_configuration = {
            'constants': {},
            'neckbeard_meta': {},
            'secrets': {},
            'secrets.tpl': {},
            'environments': {
                'foo': {},
                'bar': {},
            },
            'node_templates': {
                'ec2': {
                    'foo': {},
                    'bar': {},
                },
                'baz': {
                    'bang': {},
                },
            },
        }
        loader._validate_neckbeard_conf_version(raw_configuration)

        validation_errors = self._get_validation_errors(
            loader,
            'environments/foo.json',
            'missing_option',
        )
        self.assertEqual(len(validation_errors), 1)

        expected_error_count = 4 + 2 + 3  # Root + environments + templates
        self.assertEqual(len(loader.validation_errors), expected_error_count)

        # Now let's try the "everything is kosher" case
        correct_configuration = {
            'constants': {
                'neckbeard_conf_version': '0.1',
            },
            'neckbeard_meta': {
                'neckbeard_conf_version': '0.1',
            },
            'secrets': {
                'neckbeard_conf_version': '0.1',
            },
            'secrets.tpl': {
                'neckbeard_conf_version': '0.1',
            },
            'environments': {
                'foo': {
                    'neckbeard_conf_version': '0.1',
                },
                'bar': {
                    'neckbeard_conf_version': '0.1',
                },
            },
            'node_templates': {
                'ec2': {
                    'foo': {
                        'neckbeard_conf_version': '0.1',
                    },
                    'bar': {
                        'neckbeard_conf_version': '0.1',
                    },
                },
                'baz': {
                    'bang': {
                        'neckbeard_conf_version': '0.1',
                    },
                },
            },
        }
        loader.validation_errors = {}
        loader._validate_neckbeard_conf_version(correct_configuration)
        self.assertEqual(len(loader.validation_errors), 0)
