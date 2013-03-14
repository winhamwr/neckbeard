from __future__ import absolute_import

import argparse
import logging
import os.path

from neckbeard.loader import NeckbeardLoader

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

    loader = NeckbeardLoader(
        configuration_directory=os.path.abspath(args.configuration_directory),
    )
    configuration = loader.get_neckbeard_configuration()
    if configuration is None:
        exit(1)


# This idiom means the below code only runs when executed from command line
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    main()

