from __future__ import absolute_import

import argparse
import logging
import os.path

from neckbeard.loader import NeckbeardLoader
from neckbeard.configuration import ConfigurationManager

logger = logging.getLogger('cli')

COMMANDS = ['check']


def main():
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description='Deploy all the things!')
    parser.add_argument(
        'command',
        nargs='?',
        choices=COMMANDS,
        default='check',
        help="The neckbeard action you'd like to take",
    )
    parser.add_argument(
        '-e',
        '--environment',
        dest='environment',
        help='The deployment environment on which to operate',
    )
    parser.add_argument(
        '-c',
        '--configuration-directory',
        dest='configuration_directory',
        default='.neckbeard/',
        help="Path to your '.neckbeard' configuration directory",
    )

    args = parser.parse_args()
    return_code = run_commands(**args)
    exit(return_code)


def run_commands(command, environment, configuration_directory):
    configuration_directory = os.path.abspath(configuration_directory)

    loader = _get_and_test_loader(configuration_directory)
    if loader is None:
        return 1

    configuration = _get_and_test_configuration(loader)
    if configuration is None:
        return 1

    if command == 'check':
        do_configuration_check(
            configuration_directory,
            environment,
            configuration,
        )
        return 0


def do_configuration_check(
    configuration_directory, environment_name, configuration,
):
    print "Configuration for %s checks out A-ok!" % environment_name
    output_dir = os.path.join(
        configuration_directory, '.expanded_config', environment_name,
    )
    print "You can see the deets on your nodes in: %s" % output_dir
    configuration.dump_environment_configuration(
        environment_name,
        output_dir,
    )


def _get_and_test_loader(configuration_directory):
    loader = NeckbeardLoader(
        configuration_directory=configuration_directory,
    )
    if not loader.configuration_is_valid():
        loader.print_validation_errors()
        return None

    return loader


def _get_and_test_configuration(loader):
    configuration = ConfigurationManager.from_loader(loader)
    if not configuration.is_valid():
        configuration.print_validation_errors()
        return None

    return configuration


# This idiom means the below code only runs when executed from command line
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    main()
