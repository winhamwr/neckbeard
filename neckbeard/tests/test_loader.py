
import unittest
from os import path

from neckbeard.loader import NeckbeardLoader

FIXTURE_CONFIGS_DIR = path.abspath(
    path.join(path.dirname(__file__), 'fixture_configs'),
)

class TestFileLoading(unittest.TestCase):

    def _get_loader_for_fixture(self, fixture_name):
        configuration_directory = path.join(FIXTURE_CONFIGS_DIR, fixture_name)

        return NeckbeardLoader(configuration_directory)

    def _get_validation_errors(self, loader, config_file, error_type=None):
        full_fp = path.join(loader.configuration_directory, config_file)
        if full_fp not in loader.validation_errors:
            return []

        if error_type is None:
            return loader.validation_errors[full_fp]

        if error_type not in loader.validation_errors[full_fp]:
            return []

        return loader.validation_errors[full_fp][error_type]

    def test_all_files_loaded(self):
        # Ensure that a load on a minimally-valid configuration results in the
        # expected JSON configuration objects
        loader = self._get_loader_for_fixture('minimal')

        self.assertTrue(loader.configuration_is_valid())

        # We should have loaded both environments
        environments = ['beta', 'production']
        for environment_name in environments:
            self.assertTrue(
                loader.raw_configuration['environments'].has_key(
                    environment_name,
                ),
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
        for aws_type, expected_node_templates in expected_node_templates.items():
            node_templates_for_type = node_templates[aws_type]
            for expected_node_template in expected_node_templates:
                self.assertTrue(
                    expected_node_template in node_templates_for_type,
                )
            self.assertEqual(
                len(node_templates_for_type),
                len(expected_node_templates),
            )

    def test_json_to_dict(self):
        # Ensure that all of the JSON files have been converted to python
        # dictionaries
        loader = self._get_loader_for_fixture('minimal')

        self.assertTrue(loader.configuration_is_valid())

        # Ensure things are dictionaries by treating them as such. One from
        # each type of file
        self.assertEqual(
            loader.raw_configuration['constants'].get('neckbeard_conf_version'),
            '0.1',
        )
        self.assertEqual(
            loader.raw_configuration['secrets'].get('neckbeard_conf_version'),
            '0.1',
        )
        self.assertEqual(
            loader.raw_configuration['secrets.tpl'].get('neckbeard_conf_version'),
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

    def test_invalid_path(self):
        # We give a nice error if the `configuration_directory` doesn't exist
        # or we can't access it
        loader = self._get_loader_for_fixture('does_not_exist')

        self.assertFalse(loader.configuration_is_valid())

        self.assertEqual(len(loader.validation_errors), 1)

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

    def test_missing_files(self):
        # We should ensure that all of the required files are present
        loader = self._get_loader_for_fixture('empty')

        self.assertFalse(loader.configuration_is_valid())

        validation_errors = self._get_validation_errors(
            loader,
            'constants.json',
            'missing_file',
        )
        print loader.validation_errors
        self.assertEqual(len(validation_errors), 1)
        validation_errors = self._get_validation_errors(
            loader,
            'secrets.json',
            'missing_file',
        )
        self.assertEqual(len(validation_errors), 1)
        validation_errors = self._get_validation_errors(
            loader,
            'secrets.tpl.json',
            'missing_file',
        )
        self.assertEqual(len(validation_errors), 1)
        validation_errors = self._get_validation_errors(
            loader,
            'environments',
            'missing_environment',
        )
        self.assertEqual(len(validation_errors), 1)

    def test_node_aws_type_mismatch(self):
        # We should ensure that `node_aws_type` matches the directory where the
        # node_template JSON file lives
        assert False

    def test_node_template_name_mismatch(self):
        # We should ensure that `node_template_name` matches the filename
        # (minus JSON) where the node_template JSON file lives
        assert False

    def test_environment_name_mismatch(self):
        # We should ensure that, for environments, the `name` matches the filename
        # (minus JSON) where the JSON file lives
        assert False

    def test_neckbeard_conf_version_required(self):
        # All configs everywhere need a `neckbeard_conf_version`
        assert False

    def test_node_templates_not_required(self):
        # If no node templates exist or none exist of a particular type, that's
        # not a problem
        assert False
