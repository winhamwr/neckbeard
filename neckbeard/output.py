import logging

import boto

from neckbeard.terminal_colors import format_color, BLUE, GREEN, DARK_GRAY, RED

fab_out_opts = {
    logging.NOTSET: [],
    logging.DEBUG: [],
    logging.INFO: ['running', 'stdout'],
    logging.WARN: ['running', 'stdout'],
    logging.CRITICAL: ['running', 'stdout', 'warnings']
}
fab_quiet_opts = {
    logging.NOTSET: [],
    logging.DEBUG: [],
    logging.INFO: ['running', 'stdout', 'stderr', 'warnings'],
    logging.WARN: ['running', 'stdout', 'stderr', 'warnings'],
    logging.CRITICAL: ['running', 'stdout', 'stderr', 'warnings']
}
DEFAULT_LOG_LEVEL = logging.INFO

LEVEL_COLORS = {
    'WARNING': BLUE,
    'INFO': GREEN,
    'DEBUG': DARK_GRAY,
    'CRITICAL': RED,
    'ERROR': RED
}

LOGGERS = [
    'cli',
    'configuration',
    'loader',
    'environment_manager',
    'actions.view',
    'actions.up',
    'timer',
]


class ColoredFormatter(logging.Formatter):
    def format(self, record):
        levelname = record.levelname
        color = LEVEL_COLORS.get(levelname)
        if color is not None:
            record.levelname = format_color(levelname, color)
        return logging.Formatter.format(self, record)

colored_formatter = ColoredFormatter(
    "%(asctime)s%(levelname)s:%(name)s:%(message)s", "%M:%S"
)


class TimingFormatter(logging.Formatter):
    """
    Make the name part gray.
    """
    def format(self, record):
        record.name = format_color(record.name, DARK_GRAY)

        return logging.Formatter.format(self, record)


timer_formatter = TimingFormatter("%(name)s:%(message)s")


def configure_logging(level=logging.INFO):
    """
    Configure the default logging output for all of the neckbeard modules.
    """
    logging.basicConfig()

    console_handler = logging.StreamHandler()
    console_handler.setLevel(DEFAULT_LOG_LEVEL)
    console_handler.setFormatter(colored_formatter)

    for logger_name in LOGGERS:
        logger = logging.getLogger(logger_name)
        logger.setLevel(DEFAULT_LOG_LEVEL)
        logger.addHandler(console_handler)
        logger.parent = None

    boto.log.setLevel(logging.CRITICAL)

    # Set up the timing logger
    timer_handler = logging.StreamHandler()
    timer_handler.setLevel(DEFAULT_LOG_LEVEL)
    timer_handler.setFormatter(timer_formatter)

    timer_logger = logging.getLogger('timer')
    timer_logger.setLevel(DEFAULT_LOG_LEVEL)
    timer_logger.addHandler(timer_handler)
    timer_logger.parent = None
