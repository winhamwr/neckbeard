from __future__ import absolute_import

import argparse
import logging
import os.path

from neckbeard.actions import up, view
from neckbeard.configuration import ConfigurationManager
from neckbeard.loader import NeckbeardLoader
from neckbeard.output import configure_logging
from neckbeard.resource_tracker import build_tracker_from_config

logger = logging.getLogger('cli')

COMMANDS = [
    'check',
    'up',
    'view',
]

COMMAND_ERROR_CODES = {
    'INVALID_COMMAND_OPTIONS': 2,
}


class VerboseAction(argparse.Action):
    """
    Allow more -v options to increase verbosity while also allowing passing an
    integer argument to set verbosity.
    """
    def __call__(self, parser, args, values, option_string=None):
        if values is None:
            values = '1'

        try:
            verbosity = int(values)
        except ValueError:
            # The default is 1, so one -v should be 2
            verbosity = values.count('v') + 1

        if verbosity > 3:
            verbosity = 3

        setattr(args, self.dest, verbosity)

VERBOSITY_MAPPING = {
    0: logging.CRITICAL,
    1: logging.WARNING,
    2: logging.INFO,
    3: logging.DEBUG,
}


def main():
    parser = argparse.ArgumentParser(description='Deploy all the things!')
    parser.add_argument(
        '-v',
        '--verbosity',
        nargs='?',
        action=VerboseAction,
        default=1,
        dest='verbosity',
    )
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

    configure_logging(level=VERBOSITY_MAPPING[args.verbosity])

    return_code = run_commands(
        args.command,
        args.environment,
        args.configuration_directory,
    )
    exit(return_code)


def run_commands(command, environment, configuration_directory):
    configuration_directory = os.path.abspath(configuration_directory)

    loader = _get_and_test_loader(configuration_directory)
    if loader is None:
        return 1

    configuration = _get_and_test_configuration(loader)
    if configuration is None:
        return 1

    if environment is None:
        # If no environment is given, but there's only one environment
        # available, just go ahead and use it
        available_environments = configuration.get_available_environments()
        if len(available_environments) == 1:
            environment = available_environments[0]
        else:
            logger.critical(
                (
                    "An environment option is required. "
                    "Available options: %s"
                ),
                available_environments,
            )
            return COMMAND_ERROR_CODES['INVALID_COMMAND_OPTIONS']

    if command == 'check':
        do_configuration_check(
            configuration_directory,
            environment,
            configuration,
        )
        return 0
    elif command == 'up':
        do_up(
            configuration_directory,
            environment,
            configuration,
        )
        return 0
    elif command == 'view':
        do_view(
            configuration_directory,
            environment,
            configuration,
        )
        return 0


def do_configuration_check(
    configuration_directory, environment_name, configuration,
):
    logger.info("Configuration for %s checks out A-ok!", environment_name)
    output_dir = os.path.join(
        configuration_directory, '.expanded_config', environment_name,
    )
    logger.info("You can see the deets on your nodes in: %s", output_dir)
    configuration.dump_environment_config(
        environment_name,
        output_dir,
    )


def do_up(
    configuration_directory, environment_name, configuration,
):
    logger.info("Running up on environment: %s", environment_name)
    up(
        environment_name=environment_name,
        configuration_manager=configuration,
        resource_tracker=build_tracker_from_config(configuration),
    )


def do_view(
    configuration_directory, environment_name, configuration,
):
    logger.info("Running view on environment: %s", environment_name)
    view(
        environment_name=environment_name,
        configuration_manager=configuration,
        resource_tracker=build_tracker_from_config(configuration),
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
    main()
