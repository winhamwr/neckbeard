
import unittest
from os import path

from neckbeard.loader import NeckbeardLoader
from neckbeard.configuration import (
    ConfigurationManager,
    CircularSeedEnvironmentError,
)


class TestConfigContext(unittest.TestCase):
    def test_environment_constants(self):
        constants = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'environments': {
                'test1': {
                    'foo1': 'v_foo1',
                },
                'test2': {
                    'foo2': 'v_foo2',
                },
            },
        }
        configuration = ConfigurationManager(
            constants=constants,
            secrets={},
            secrets_tpl={},
            environments={},
            node_templates={},
        )

        test1_constants = configuration._get_environment_constants('test1')
        self.assertEqual(len(test1_constants), 1)
        self.assertEqual(test1_constants['foo1'], 'v_foo1')

        test2_constants = configuration._get_environment_constants('test2')
        self.assertEqual(len(test2_constants), 1)
        self.assertEqual(test2_constants['foo2'], 'v_foo2')

    def test_environment_secrets(self):
        secrets = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'environments': {
                'test1': {
                    'foo1': 'v_foo1',
                },
                'test2': {
                    'foo2': 'v_foo2',
                },
            },
        }
        configuration = ConfigurationManager(
            constants={},
            secrets=secrets,
            secrets_tpl={},
            environments={},
            node_templates={},
        )

        secrets = configuration._get_environment_secrets('test1')
        self.assertEqual(len(secrets), 1)
        self.assertEqual(secrets['foo1'], 'v_foo1')

        secrets = configuration._get_environment_secrets('test2')
        self.assertEqual(len(secrets), 1)
        self.assertEqual(secrets['foo2'], 'v_foo2')

    def test_seed_environment(self):
        constants = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'environments': {
                'test1': {
                    'foo': 'v_foo1',
                },
                'test2': {
                    'foo': 'v_foo2',
                },
            },
        }
        secrets = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'environments': {
                'test1': {
                    'secret_foo': 'v_secret_foo1',
                },
                'test2': {
                    'secret_foo': 'v_secret_foo2',
                },
            },
        }
        environments = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'test1': {
                'seed_environment_name': 'test2',
                'aws_nodes': {
                    'ec2': {
                        'web': {
                            'name': 'web',
                        },
                    },
                },
            },
            'test2': {
                'aws_nodes': {
                    'ec2': {
                        'web': {
                            'name': 'web',
                        },
                    },
                },
            },
        }
        configuration = ConfigurationManager(
            constants=constants,
            secrets=secrets,
            secrets_tpl={},
            environments=environments,
            node_templates={},
        )

        # Check constants
        constants = configuration._get_seed_environment_constants('test1')
        self.assertEqual(len(constants), 1)
        self.assertEqual(constants['foo'], 'v_foo2')

        # Check secrets
        secrets = configuration._get_seed_environment_secrets('test1')
        self.assertEqual(len(secrets), 1)
        self.assertEqual(secrets['secret_foo'], 'v_secret_foo2')

    def test_seed_environment_not_set(self):
        environments = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'test1': {
                'seed_environment_name': 'test2',
                'aws_nodes': {
                    'ec2': {
                        'web': {
                            'name': 'web',
                        },
                    },
                },
            },
            'test2': {
                'aws_nodes': {
                    'ec2': {
                        'web': {
                            'name': 'web',
                        },
                    },
                },
            },
        }
        configuration = ConfigurationManager(
            constants={},
            secrets={},
            secrets_tpl={},
            environments=environments,
            node_templates={},
        )

        # Check constants
        constants = configuration._get_seed_environment_constants('test2')
        self.assertEqual(constants, {})

        # Check secrets
        secrets = configuration._get_seed_environment_secrets('test2')
        self.assertEqual(secrets, {})

    def test_circular_seed_environment(self):
        environments = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'test1': {
                'seed_environment_name': 'test2',
                'aws_nodes': {
                    'ec2': {
                        'web': {
                            'name': 'web',
                        },
                    },
                },
            },
            'test2': {
                'seed_environment_name': 'test3',
                'aws_nodes': {
                    'ec2': {
                        'web': {
                            'name': 'web',
                        },
                    },
                },
            },
            'test3': {
                'seed_environment_name': 'test1',
                'aws_nodes': {
                    'ec2': {
                        'web': {
                            'name': 'web',
                        },
                    },
                },
            },
        }
        configuration = ConfigurationManager(
            constants={},
            secrets={},
            secrets_tpl={},
            environments=environments,
            node_templates={},
        )

        self.assertRaises(
            CircularSeedEnvironmentError,
            configuration._get_seed_environment_constants,
            'test1',
        )
        self.assertRaises(
            CircularSeedEnvironmentError,
            configuration._get_seed_environment_constants,
            'test2',
        )

        self.assertRaises(
            CircularSeedEnvironmentError,
            configuration._get_seed_environment_secrets,
            'test1',
        )
        self.assertRaises(
            CircularSeedEnvironmentError,
            configuration._get_seed_environment_secrets,
            'test2',
        )

    def test_node(self):
        raise NotImplementedError()

    def test_seed_node(self):
        raise NotImplementedError()

    def test_circular_seed_node(self):
        raise NotImplementedError()

    def test_full_config_context(self):
        constants = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'environments': {
                'test1': {
                    'foo1': 'v_foo1',
                },
            },
        }
        secrets = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'environments': {
                'test1': {
                    'secret1': 'v_secret1',
                },
            },
        }
        secrets_tpl = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'environments': {
                'test1': {
                    'secret1': None,
                },
            },
        }
        environments = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'test1': {
                'name': 'test1',
                'aws_nodes': {
                    'ec2': {
                        'web': {
                            "name": "web",
                            "unique_id": "web-{{ node.index_for_scaling_group }}",
                        },
                    },
                },
            },
        }
        configuration = ConfigurationManager(
            constants=constants,
            secrets=secrets,
            secrets_tpl=secrets_tpl,
            environments=environments,
            node_templates={},
        )

        context = configuration.get_config_context_for_resource(
            environment='test1',
            resource_type='ec2',
            name='web',
            index=0,
        )
        expected_variables = [
            'environment',
            'seed_environment',
            'node',
            'seed_node',
        ]
        self.assertEqual(sorted(context.keys()), sorted(expected_variables))

        self.assertEqual(context['environment']['constants']['foo1'], 'v_foo1')
        self.assertEqual(
            context['environment']['secrets']['secret1'],
            'v_secret1',
        )

        self.assertEqual(
            context['node'],
            {'name': 'web', 'index_for_scaling_group': 0},
        )

        # No seed stuff configured
        self.assertEqual(context['seed_environment'], {})
        self.assertEqual(context['seed_node'], {})


class TestNodeTemplateExpansion(unittest.TestCase):

    def test_no_template(self):
        # Nodes without a template still work
        raise NotImplementedError()


