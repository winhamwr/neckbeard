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

    configuration_directory = os.path.abspath(args.configuration_directory)
    loader = NeckbeardLoader(
        configuration_directory=configuration_directory,
    )
    if not loader.configuration_is_valid():
        loader.print_validation_errors()
        exit(1)

    raw_config = loader.raw_configuration
    configuration = ConfigurationManager(
        constants=raw_config['constants'],
        secrets=raw_config['secrets'],
        secrets_tpl=raw_config['secrets_tpl'],
        environments=raw_config['environments'],
        node_templates=raw_config['environments'],
    )
    if not configuration.is_valid():
        configuration.print_validation_errors()
        exit(1)

    if args.command == 'check':
        print "Configuration checks out A-ok!"
        output_dir = os.path.join(
            configuration_directory, '.expanded_config')
        print "You can see the deets on your nodes in: %s" % output_dir
        configuration.dump_node_configurations(output_dir)
        exit(0)


# This idiom means the below code only runs when executed from command line
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    main()

