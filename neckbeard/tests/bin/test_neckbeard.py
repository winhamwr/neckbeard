
import unittest2
from os import path

import mock
import boto.exception

from neckbeard.bin.neckbeard import run_commands

FIXTURE_CONFIGS_DIR = path.abspath(
    path.join(path.dirname(__file__), '../fixture_configs'),
)


class TestRunCommands(unittest2.TestCase):
    def test_check(self):
        # Let's use the minimal configs
        configuration_dir = path.join(FIXTURE_CONFIGS_DIR, 'minimal')

        return_code = run_commands('check', 'beta', configuration_dir)
        self.assertEqual(return_code, 0)

    def test_view(self):
        # Let's use the minimal configs
        configuration_dir = path.join(FIXTURE_CONFIGS_DIR, 'minimal')

        with mock.patch(
            'neckbeard.resource_tracker.simpledb.SimpleDB',
            autospec=True,
        ):
            # Until we can either mock out boto with a version of moto that
            # supports python 2.6 or we create a local/mockable
            # ResourceTracker, we can only test that we try to authenticate
            # with boto and then break. That counts as passing, for now.
            self.assertRaises(
                boto.exception.NoAuthHandlerFound,
                run_commands,
                'view',
                'beta',
                configuration_dir,
            )
