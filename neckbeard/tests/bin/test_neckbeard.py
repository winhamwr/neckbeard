
import unittest2
from os import path

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

        return_code = run_commands('view', 'beta', configuration_dir)
        self.assertEqual(return_code, 0)
