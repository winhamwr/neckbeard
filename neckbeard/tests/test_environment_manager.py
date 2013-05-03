import mock
import unittest2

from neckbeard.environment_manager import (
    Deployment,
    MissingAWSCredentials,
    NonUniformAWSCredentials,
)


class TestConfigValidation(unittest2.TestCase):
    def test_differing_aws_credentials(self):
        ec2_configs = {
            'web0-0': {
                "name": "web0",
                "unique_id": "web0-0",
                "aws": {
                    "access_key_id": "FOO",
                    "secret_access_key": "FOO",
                },
            },
        }
        rds_configs = {
            'web1-0': {
                "name": "web1",
                "unique_id": "web1-0",
                "aws": {
                    "access_key_id": "BAR",
                    "secret_access_key": "BAR",
                },
            },
        }
        self.assertRaises(
            NonUniformAWSCredentials,
            lambda: Deployment('test', ec2_configs, rds_configs, {}),
        )

    def test_aws_credentials_none(self):
        none_configs = {
            'web0-0': {
                "name": "web0",
                "unique_id": "web0-0",
                "aws": {
                    "access_key_id": None,
                    "secret_access_key": None,
                },
            },
        }
        self.assertRaises(
            MissingAWSCredentials,
            lambda: Deployment('test', none_configs, {}, {}),
        )

    def test_no_aws_level(self):
        missing_aws_configs = {
            'web0-0': {
                "name": "web0",
                "unique_id": "web0-0",
            },
        }
        self.assertRaises(
            MissingAWSCredentials,
            lambda: Deployment('test', missing_aws_configs, {}, {}),
        )

    def test_no_aws_access_key(self):
        no_access_key = {
            'web0-0': {
                "name": "web0",
                "unique_id": "web0-0",
                "aws": {
                    "secret_access_key": "FOO",
                },
            },
        }
        self.assertRaises(
            MissingAWSCredentials,
            lambda: Deployment('test', no_access_key, {}, {}),
        )

    def test_no_aws_secret_key(self):
        no_secret_key = {
            'web0-0': {
                "name": "web0",
                "unique_id": "web0-0",
                "aws": {
                    "access_key_id": "FOO",
                },
            },
        }
        self.assertRaises(
            MissingAWSCredentials,
            lambda: Deployment('test', no_secret_key, {}, {}),
        )

    def test_boto_connections_created(self):
        # If the AWS credentials are valid, those credentials are used to
        # create connections
        ec2_configs = {
            'web0-0': {
                "name": "web0",
                "unique_id": "web0-0",
                "aws": {
                    "access_key_id": "FOO",
                    "secret_access_key": "FOO",
                },
            },
        }
        rds_configs = {
            'web1-0': {
                "name": "web1",
                "unique_id": "web1-0",
                "aws": {
                    "access_key_id": "FOO",
                    "secret_access_key": "FOO",
                },
            },
        }

        with mock.patch('boto.auth.get_auth_handler', autospec=True):
            deployment = Deployment('test', ec2_configs, rds_configs, {})
        self.assertNotEqual(deployment.ec2conn, None)
        self.assertNotEqual(deployment.rdsconn, None)

        for conn in [deployment.ec2conn, deployment.rdsconn]:
            self.assertEqual(conn.access_key, 'FOO')
            self.assertEqual(conn.secret_key, 'FOO')
