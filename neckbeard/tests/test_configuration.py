
import unittest
from os import path

from neckbeard.loader import NeckbeardLoader
from neckbeard.configuration import (
    ConfigurationManager,
    CircularSeedEnvironmentError,
)

class MaxScalingManager(object):
    """
    A scaling manager that always assumes the maximum allowed number of nodes
    is the current scale.
    """
    def get_indexes_for_resource(self,
            environment, resource_type, resource_name, resource_configuration):

        scaling = resource_configuration.get('scaling')
        if not scaling:
            return 1

        return scaling.get('maximum', 1)


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
            scaling_manager=MaxScalingManager(),
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
            scaling_manager=MaxScalingManager(),
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
            scaling_manager=MaxScalingManager(),
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
            scaling_manager=MaxScalingManager(),
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
            scaling_manager=MaxScalingManager(),
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
        environments = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'test1': {
                'name': 'test1',
                'seed_environment_name': 'test2',
                'aws_nodes': {
                    'ec2': {
                        'web': {
                            "name": "web",
                            "unique_id": "web-{{ node.index_for_scaling_group }}",
                            "seed": {
                                "name": "web",
                                "index_for_scaling_group": 0,
                            },
                        },
                    },
                },
            },
            'test2': {
                'name': 'test2',
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
            constants={},
            secrets={},
            secrets_tpl={},
            environments=environments,
            node_templates={},
            scaling_manager=MaxScalingManager(),
        )

        node_context = configuration._get_node_context('test1', 'ec2', 'web', 1)
        expected = {
            'environment_name': 'test1',
            'seed_environment_name': 'test2',
            'resource_type': 'ec2',
            'name': 'web',
            'index_for_scaling_group': 1,
        }

    def test_node_not_zero(self):
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
            constants={},
            secrets={},
            secrets_tpl={},
            environments=environments,
            node_templates={},
            scaling_manager=MaxScalingManager(),
        )

        node_context = configuration._get_node_context('test1', 'ec2', 'web', 7)
        expected = {
            'environment_name': 'test1',
            'seed_environment_name': None,
            'resource_type': 'ec2',
            'name': 'web',
            'index_for_scaling_group': 7,
        }
        self.assertEqual(len(node_context), len(expected))
        for key, value in expected.items():
            self.assertEqual(node_context.get(key), value)

    def test_seed_node(self):
        environments = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'test1': {
                'name': 'test1',
                'seed_environment_name': 'test3',
                'aws_nodes': {
                    'ec2': {
                        'web': {
                            "name": "web",
                            "unique_id": "web-{{ node.index_for_scaling_group }}",
                            "seed": {
                                "name": "web",
                                "index_for_scaling_group": 3,
                            },
                        },
                    },
                },
            },
            'test2': {
                'name': 'test2',
                'seed_environment_name': 'test3',
                'aws_nodes': {
                    'ec2': {
                        'web': {
                            "name": "web",
                            "unique_id": "web-{{ node.index_for_scaling_group }}",
                            "seed": {
                                "name": "web",
                            },
                        },
                    },
                },
            },
            'test3': {
                'name': 'test3',
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
            constants={},
            secrets={},
            secrets_tpl={},
            environments=environments,
            node_templates={},
            scaling_manager=MaxScalingManager(),
        )

        # Explicit seed values
        node_context = configuration._get_seed_node_context(
            'test1',
            'ec2',
            'web',
            3,
        )
        expected = {
            'environment_name': 'test3',
            'seed_environment_name': None,
            'resource_type': 'ec2',
            'name': 'web',
            'index_for_scaling_group': 3,
        }
        self.assertEqual(len(node_context), len(expected))
        for key, value in expected.items():
            self.assertEqual(node_context.get(key), value)

        # Implicit seed values
        node_context = configuration._get_seed_node_context(
            'test2',
            'ec2',
            'web',
            0,
        )
        expected = {
            'environment_name': 'test3',
            'seed_environment_name': None,
            'resource_type': 'ec2',
            'name': 'web',
            'index_for_scaling_group': 0,
        }
        self.assertEqual(len(node_context), len(expected))
        for key, value in expected.items():
            self.assertEqual(node_context.get(key), value)

    def test_no_seed_node(self):
        environments = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'test1': {
                'name': 'test1',
                'seed_environment_name': 'test2',
                'aws_nodes': {
                    'ec2': {
                        'web': {
                            "name": "web",
                            "unique_id": "web-{{ node.index_for_scaling_group }}",
                            "seed": {},
                        },
                    },
                },
            },
            'test2': {
                'name': 'test2',
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
            constants={},
            secrets={},
            secrets_tpl={},
            environments=environments,
            node_templates={},
            scaling_manager=MaxScalingManager(),
        )

        node_context = configuration._get_seed_node_context(
            'test1',
            'ec2',
            'web',
            0,
        )
        self.assertEqual(len(node_context), 0)

    def test_circular_seed_node(self):
        environments = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'test1': {
                'name': 'test1',
                'seed_environment_name': 'test2',
                'aws_nodes': {
                    'ec2': {
                        'web': {
                            "name": "web",
                            "unique_id": "web-{{ node.index_for_scaling_group }}",
                            "seed": {
                                "name": "web",
                            },
                        },
                    },
                },
            },
            'test2': {
                'name': 'test2',
                'seed_environment_name': 'test3',
                'aws_nodes': {
                    'ec2': {
                        'web': {
                            "name": "web",
                            "unique_id": "web-{{ node.index_for_scaling_group }}",
                            "seed": {
                                "name": "web",
                            },
                        },
                    },
                },
            },
            'test3': {
                'name': 'test3',
                'aws_nodes': {
                    'ec2': {
                        'web': {
                            "name": "web",
                            "unique_id": "web-{{ node.index_for_scaling_group }}",
                            "seed": {
                                "name": "web",
                            },
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
            scaling_manager=MaxScalingManager(),
        )

        self.assertRaises(
            CircularSeedEnvironmentError,
            configuration._get_seed_node_context,
            'test1',
            'ec2',
            'web',
            0,
        )

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
            scaling_manager=MaxScalingManager(),
        )

        context = configuration._get_config_context_for_resource(
            environment='test1',
            resource_type='ec2',
            name='web',
            index_for_scaling_group=0,
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
            context['node']['name'],
            'web',
        )
        self.assertEqual(
            context['node']['index_for_scaling_group'],
            0,
        )

        # No seed stuff configured
        self.assertEqual(context['seed_environment']['secrets'], {})
        self.assertEqual(context['seed_environment']['constants'], {})
        self.assertEqual(context['seed_node'], {})


class TestResourceTemplateApplication(unittest.TestCase):

    def test_no_template(self):
        # Nodes without a template still work
        environments = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'test1': {
                'name': 'test1',
                'aws_nodes': {
                    'ec2': {
                        'web0': {
                            "name": "web0",
                            "unique_id": "web0-{{ node.index_for_scaling_group }}",
                        },
                    },
                },
            },
        }
        node_templates = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'ec2': {},
        }

        configuration = ConfigurationManager(
            environments=environments,
            node_templates=node_templates,
            scaling_manager=MaxScalingManager(),
        )
        expanded_conf = configuration._apply_resource_template(
            'ec2',
            environments['test1']['aws_nodes']['ec2']['web0'],
        )
        self.assertEqual(expanded_conf['name'], 'web0')

    def test_variables_added(self):
        environments = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'test1': {
                'name': 'test1',
                'aws_nodes': {
                    'ec2': {
                        'web0': {
                            "name": "web0",
                            "resource_template_name": "web",
                            "unique_id": "web-{{ node.index_for_scaling_group }}",
                        },
                    },
                },
            },
        }
        node_templates = {
            'ec2': {
                "web": {
                    NeckbeardLoader.VERSION_OPTION: '0.1',
                    "resource_type": "ec2",
                    "resource_template_name": "web",
                    "defaults": {
                        "foo1": "v_foo1",
                    },
                    "required_overrides": {},
                },
            },
        }

        configuration = ConfigurationManager(
            environments=environments,
            node_templates=node_templates,
            scaling_manager=MaxScalingManager(),
        )
        expanded_conf = configuration._apply_resource_template(
            'ec2',
            environments['test1']['aws_nodes']['ec2']['web0'],
        )
        self.assertEqual(expanded_conf.get('foo1'), 'v_foo1')

    def test_resource_preference(self):
        # Things in the config take preference over things in the template
        environments = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'test1': {
                'name': 'test1',
                'aws_nodes': {
                    'ec2': {
                        'web0': {
                            "name": "web0",
                            "resource_template_name": "web",
                            "unique_id": "web-{{ node.index_for_scaling_group }}",
                            "foo": "original",
                        },
                    },
                },
            },
        }
        node_templates = {
            'ec2': {
                "web": {
                    NeckbeardLoader.VERSION_OPTION: '0.1',
                    "resource_type": "ec2",
                    "resource_template_name": "web",
                    "defaults": {
                        "foo": "template",
                    },
                    "required_overrides": {},
                },
            },
        }

        configuration = ConfigurationManager(
            environments=environments,
            node_templates=node_templates,
            scaling_manager=MaxScalingManager(),
        )
        expanded_conf = configuration._apply_resource_template(
            'ec2',
            environments['test1']['aws_nodes']['ec2']['web0'],
        )
        self.assertEqual(expanded_conf['foo'], 'original')

    def test_deep_merge(self):
        # Dictionaries are deep merged
        environments = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'test1': {
                'name': 'test1',
                'aws_nodes': {
                    'ec2': {
                        'web0': {
                            "name": "web0",
                            "resource_template_name": "web",
                            "unique_id": "web-{{ node.index_for_scaling_group }}",
                            "service_addons": {
                                "redis": {
                                    "foo": "original",
                                },
                            },
                        },
                    },
                },
            },
        }
        node_templates = {
            'ec2': {
                "web": {
                    NeckbeardLoader.VERSION_OPTION: '0.1',
                    "resource_type": "ec2",
                    "resource_template_name": "web",
                    "defaults": {
                        "service_addons": {
                            "redis": {
                                "foo": "overridden",
                                "from_template": "v_from_template",
                            },
                            "celery": {
                                "celerybeat": True,
                            },
                        },
                    },
                    "required_overrides": {},
                },
            },
        }

        configuration = ConfigurationManager(
            environments=environments,
            node_templates=node_templates,
                            "resource_template_name": "web",
            scaling_manager=MaxScalingManager(),
        )
        expanded_conf = configuration._apply_resource_template(
            'ec2',
            environments['test1']['aws_nodes']['ec2']['web0'],
        )
        service_addons = expanded_conf.get("service_addons", {})
        celery = service_addons.get('celery', {})
        self.assertEqual(celery.get('celerybeat'), True)
        redis = service_addons.get('redis', {})
        self.assertEqual(redis.get('foo'), "original")
        self.assertEqual(redis.get('from_template'), "v_from_template")

