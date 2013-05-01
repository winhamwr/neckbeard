
import json
import shutil
import tempfile
import unittest2
from os import path

from neckbeard.loader import NeckbeardLoader
from neckbeard.configuration import (
    ConfigurationManager,
    CircularSeedEnvironmentError,
)
from neckbeard.scaling import MaxScalingBackend


class TestConfigContext(unittest2.TestCase):
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
            scaling_backend=MaxScalingBackend(),
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
            scaling_backend=MaxScalingBackend(),
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
            scaling_backend=MaxScalingBackend(),
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
            scaling_backend=MaxScalingBackend(),
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
            scaling_backend=MaxScalingBackend(),
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
                            "unique_id": "web-{{ node.scaling_index }}",
                            "seed": {
                                "name": "web",
                                "scaling_index": 0,
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
                            "unique_id": "web-{{ node.scaling_index }}",
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
            scaling_backend=MaxScalingBackend(),
        )

        node_context = configuration._get_resource_context(
            'test1', 'ec2', 'web', 1,
        )
        expected = {
            'environment_name': 'test1',
            'seed_environment_name': 'test2',
            'resource_type': 'ec2',
            'name': 'web',
            'scaling_index': 1,
        }
        self.assertEqual(node_context, expected)

    def test_node_not_zero(self):
        environments = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'test1': {
                'name': 'test1',
                'aws_nodes': {
                    'ec2': {
                        'web': {
                            "name": "web",
                            "unique_id": "web-{{ node.scaling_index }}",
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
            scaling_backend=MaxScalingBackend(),
        )

        node_context = configuration._get_resource_context(
            'test1', 'ec2', 'web', 7,
        )
        expected = {
            'environment_name': 'test1',
            'seed_environment_name': None,
            'resource_type': 'ec2',
            'name': 'web',
            'scaling_index': 7,
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
                            "unique_id": "web-{{ node.scaling_index }}",
                            "seed": {
                                "name": "web",
                                "scaling_index": 3,
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
                            "unique_id": "web-{{ node.scaling_index }}",
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
                            "unique_id": "web-{{ node.scaling_index }}",
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
            scaling_backend=MaxScalingBackend(),
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
            'scaling_index': 3,
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
            'scaling_index': 0,
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
                            "unique_id": "web-{{ node.scaling_index }}",
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
                            "unique_id": "web-{{ node.scaling_index }}",
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
            scaling_backend=MaxScalingBackend(),
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
                            "unique_id": "web-{{ node.scaling_index }}",
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
                            "unique_id": "web-{{ node.scaling_index }}",
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
                            "unique_id": "web-{{ node.scaling_index }}",
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
            scaling_backend=MaxScalingBackend(),
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
                            "unique_id": "web-{{ node.scaling_index }}",
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
            scaling_backend=MaxScalingBackend(),
        )

        context = configuration._get_config_context_for_resource(
            environment='test1',
            resource_type='ec2',
            name='web',
            scaling_index=0,
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
            context['node']['scaling_index'],
            0,
        )

        # No seed stuff configured
        self.assertEqual(len(context['seed_environment']['secrets']), 0)
        self.assertEqual(len(context['seed_environment']['constants']), 0)
        self.assertEqual(len(context['seed_node']), 0)


class TestNodeTemplateApplication(unittest2.TestCase):
    # TODO: Call this TestResourceTemplateApplication once node templates are
    # renamed

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
                            "unique_id": "web0-{{ node.scaling_index }}",
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
            scaling_backend=MaxScalingBackend(),
        )
        expanded_conf = configuration._apply_node_template(
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
                            "node_template_name": "web",
                            "unique_id": "web-{{ node.scaling_index }}",
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
                    "node_template_name": "web",
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
            scaling_backend=MaxScalingBackend(),
        )
        expanded_conf = configuration._apply_node_template(
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
                            "node_template_name": "web",
                            "unique_id": "web-{{ node.scaling_index }}",
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
                    "node_template_name": "web",
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
            scaling_backend=MaxScalingBackend(),
        )
        expanded_conf = configuration._apply_node_template(
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
                            "node_template_name": "web",
                            "unique_id": "web-{{ node.scaling_index }}",
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
                    "node_template_name": "web",
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
            scaling_backend=MaxScalingBackend(),
        )
        expanded_conf = configuration._apply_node_template(
            'ec2',
            environments['test1']['aws_nodes']['ec2']['web0'],
        )
        service_addons = expanded_conf.get("service_addons", {})
        celery = service_addons.get('celery', {})
        self.assertEqual(celery.get('celerybeat'), True)
        redis = service_addons.get('redis', {})
        self.assertEqual(redis.get('foo'), "original")
        self.assertEqual(redis.get('from_template'), "v_from_template")


class TestConfigExpansion(unittest2.TestCase):
    def test_environment_configuration(self):
        # Integration test for full environment configuration parsing
        secrets = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'environments': {
                'test1': {
                    'foo': 'v_secret1',
                },
                'test2': {
                    'foo': 'v_secret2',
                },
            },
        }
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
        environments = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'test1': {
                'name': 'test1',
                'seed_environment_name': 'test2',
                'aws_nodes': {
                    'ec2': {
                        'web0': {
                            "name": "web0",
                            "unique_id": "web0-{{ node.scaling_index }}",
                            "node_template_name": "web",
                            "seed": {
                                "name": "web",
                            },
                            "service_addons": {
                                "redis": {
                                    "foo": "web0",
                                },
                            },
                        },
                        'web1': {
                            "name": "web1",
                            "unique_id": "web1-{{ node.scaling_index }}",
                            "node_template_name": "web",
                            "seed": {
                                "name": "web",
                            },
                            "service_addons": {
                                "redis": {
                                    "foo": "web1",
                                },
                            },
                            "scaling": {
                                "minimum": 1,
                                "maximum": 2,
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
                            "unique_id": "web-{{ node.scaling_index }}",
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
                    "node_template_name": "web",
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
                        "constant_foo": "{{ environment.constants.foo }}",
                        "secret_foo": "{{ environment.secrets.foo }}",
                        "s_const_foo": "{{ seed_environment.constants.foo }}",
                        "s_secret_foo": "{{ seed_environment.secrets.foo }}",
                    },
                    "required_overrides": {},
                },
            },
        }
        configuration = ConfigurationManager(
            constants=constants,
            secrets=secrets,
            secrets_tpl={},
            environments=environments,
            node_templates=node_templates,
            scaling_backend=MaxScalingBackend(),
        )
        expanded_configuration = configuration.get_environment_config(
            'test1',
        )
        expected = {
            "ec2": {
                'web0-0': {
                    "name": "web0",
                    "unique_id": "web0-0",
                    "node_template_name": "web",
                    "seed": {
                        "name": "web",
                    },
                    "service_addons": {
                        "redis": {
                            "foo": "web0",
                            "from_template": "v_from_template",
                        },
                        "celery": {
                            "celerybeat": True,
                        },
                    },
                    "constant_foo": "v_foo1",
                    "secret_foo": "v_secret1",
                    "s_const_foo": "v_foo2",
                    "s_secret_foo": "v_secret2",
                },
                'web1-0': {
                    "name": "web1",
                    "unique_id": "web1-0",
                    "node_template_name": "web",
                    "seed": {
                        "name": "web",
                    },
                    "service_addons": {
                        "redis": {
                            "foo": "web1",
                            "from_template": "v_from_template",
                        },
                        "celery": {
                            "celerybeat": True,
                        },
                    },
                    "scaling": {
                        "minimum": 1,
                        "maximum": 2,
                    },
                    "constant_foo": "v_foo1",
                    "secret_foo": "v_secret1",
                    "s_const_foo": "v_foo2",
                    "s_secret_foo": "v_secret2",
                },
                'web1-1': {
                    "name": "web1",
                    "unique_id": "web1-1",
                    "node_template_name": "web",
                    "seed": {
                        "name": "web",
                    },
                    "service_addons": {
                        "redis": {
                            "foo": "web1",
                            "from_template": "v_from_template",
                        },
                        "celery": {
                            "celerybeat": True,
                        },
                    },
                    "scaling": {
                        "minimum": 1,
                        "maximum": 2,
                    },
                    "constant_foo": "v_foo1",
                    "secret_foo": "v_secret1",
                    "s_const_foo": "v_foo2",
                    "s_secret_foo": "v_secret2",
                },
            },
        }
        # Ensure all of the unique nodes exist
        actual_unique_ids = expanded_configuration['ec2'].keys()
        for unique_id in expected['ec2'].keys():
            self.assertTrue(
                unique_id in actual_unique_ids,
                msg="%s not in ec2 resources. Actuals: %s" % (
                    unique_id,
                    actual_unique_ids,
                ),
            )
        # Test that the individual configurations actually match
        for unique_id in expected['ec2'].keys():
            self.assertDictEqual(
                expanded_configuration['ec2'][unique_id],
                expected['ec2'][unique_id],
                msg="Config doesn't match for %s" % unique_id,
            )

    def test_config_data_types(self):
        # Lists, dictionaries, integers, strings, booleans and floats should
        # all be valid configuration values
        environments = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'test1': {
                'name': 'test1',
                'aws_nodes': {
                    'ec2': {
                        'web0': {
                            "name": "web0",
                            "unique_id": "web0-{{ node.scaling_index }}",
                            "service_addons": {
                                "list": [
                                    "item1",
                                    1,
                                    1.0,
                                    True,
                                    None,
                                ],
                                "unicode": u'unicode',
                                "int": 1,
                                "float": 110.05,
                                "bool": False,
                                "none": None,
                            },
                        },
                    },
                },
            },
        }
        configuration = ConfigurationManager(
            environments=environments,
            scaling_backend=MaxScalingBackend(),
        )
        expanded_configuration = configuration.get_environment_config(
            'test1',
        )
        expected = {
            'ec2': {
                'web0-0': {
                    "name": "web0",
                    "unique_id": "web0-0",
                    "service_addons": {
                        "list": [
                            "item1",
                            1,
                            1.0,
                            True,
                            None,
                        ],
                        "unicode": u'unicode',
                        "int": 1,
                        "float": 110.05,
                        "bool": False,
                        "none": None,
                    },
                },
            },
        }
        self.assertEqual(expanded_configuration, expected)

    def test_seeds_references_dont_error(self):
        # If a node doesn't have a seed environment/node, then no jinja
        # templates that rely on properties on those should raise errors. All
        # values will be None
        environments = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'test1': {
                'name': 'test1',
                'aws_nodes': {
                    'ec2': {
                        'web0': {
                            "name": "web0",
                            "unique_id": "web0-{{ node.scaling_index }}",
                            "env_constant": "{{ seed_environment.constants.foo }}",  # NOQA
                            "env_secret": "{{ seed_environment.secrets.foo }}",
                            "env_name": "{{ seed_environment.name }}",
                            "node_foo": "{{ seed_node.foo }}",
                        },
                    },
                },
            },
        }
        configuration = ConfigurationManager(
            environments=environments,
            scaling_backend=MaxScalingBackend(),
        )
        expanded_configuration = configuration.get_environment_config(
            'test1',
        )
        expected = {
            'ec2': {
                'web0-0': {
                    "name": "web0",
                    "unique_id": "web0-0",
                    "env_constant": "",
                    "env_secret": "",
                    "env_name": "",
                    "node_foo": "",
                },
            },
        }
        self.assertEqual(expanded_configuration, expected)

    def test_neckbeard_configuration(self):
        # Integration test for creating the full Neckbeard meta configuration
        secrets = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'neckbeard_meta': {
                'resource_tracker': {
                    'init': {
                        'foo': 'secret',
                    },
                },
            },
        }
        constants = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'neckbeard_meta': {
                'resource_tracker': {
                    'path': "neckbeard.resource_tracker.ResourceTrackerBase",  # NOQA
                },
            },
        }
        neckbeard_meta = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'resource_tracker': {
                'path': "{{ constants.resource_tracker.path }}",  # NOQA
                'init': {
                    "hard_coded": "hard_coded",
                    "secret": "{{ secrets.resource_tracker.init.foo }}",
                },
            },
        }

        configuration = ConfigurationManager(
            environments={},
            constants=constants,
            secrets=secrets,
            neckbeard_meta=neckbeard_meta,
            scaling_backend=MaxScalingBackend(),
        )
        expanded_configuration = configuration.get_neckbeard_meta_config()
        expected = {
            'resource_tracker': {
                'path': "neckbeard.resource_tracker.ResourceTrackerBase",  # NOQA
                'init': {
                    "hard_coded": "hard_coded",
                    "secret": "secret",
                },
            },
        }
        self.assertEqual(expanded_configuration, expected)


class TestFileDumping(unittest2.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def test_vanilla(self):
        environments = {
            NeckbeardLoader.VERSION_OPTION: '0.1',
            'test1': {
                'name': 'test1',
                'aws_nodes': {
                    'ec2': {
                        'web0': {
                            "name": "web0",
                            "unique_id": "web0-{{ node.scaling_index }}",
                        },
                        'web1': {
                            "name": "web1",
                            "unique_id": "web1-{{ node.scaling_index }}",
                            "scaling": {
                                "minimum": 1,
                                "maximum": 2,
                            },
                        },
                    },
                    'baz': {
                        'master': {
                            "name": "master",
                            "unique_id": "master",
                        },
                    },
                },
            },
        }
        configuration = ConfigurationManager(
            environments=environments,
            scaling_backend=MaxScalingBackend(),
        )
        output_dir = path.join(self.tmp_dir, 'test1')
        configuration.dump_environment_config(
            'test1',
            output_dir,
        )

        # Ensure we created the expected `resource_type` directories
        self.assertTrue(path.exists(output_dir))
        for resource_type in ['ec2', 'baz']:
            resource_type_dir = path.join(output_dir, resource_type)
            self.assertTrue(path.exists(resource_type_dir))

        # Ensure the individual resource JSON files exist and that they have
        # some content
        ec2_dir = path.join(output_dir, 'ec2')
        for unique_id in ['web0-0', 'web1-0', 'web1-1']:
            resource_path = path.join(ec2_dir, '%s.json' % unique_id)
            self.assertTrue(path.exists(resource_path))
            with open(resource_path, 'r') as fp:
                data = json.load(fp)
            self.assertEqual(data['unique_id'], unique_id)

        # Same thing for baz
        baz_dir = path.join(output_dir, 'baz')
        unique_id = 'master'
        resource_path = path.join(baz_dir, '%s.json' % unique_id)
        self.assertTrue(path.exists(resource_path))
        with open(resource_path, 'r') as fp:
            data = json.load(fp)
        self.assertEqual(data['unique_id'], unique_id)
