import logging
import os
from datetime import datetime

from decorator import contextmanager
from fabric.api import env, prompt

logger = logging.getLogger('actions.utils')
time_logger = logging.getLogger('timer')

PENDING = 'PENDING'
ACTIVE = 'ACTIVE'
OLD = 'OLD'
GENERATION_STATES = [PENDING, ACTIVE, OLD]


def _get_gen_target():
    generation_target = ''
    if hasattr(env, '_active_gen'):
        if env._active_gen:
            generation_target = 'ACTIVE'
        else:
            if getattr(env, '_old_gen', False):
                generation_target = 'OLD'
            else:
                generation_target = 'PENDING'
    else:
        logger.critical("Must run active, pending or old before this task")
        exit(1)

    return generation_target


def get_deployer():
    return os.environ.get(
        'POLICYSTAT_DEPLOYER_NAME',
        os.environ.get('USER', 'unknown'),
    )


@contextmanager
def prompt_on_exception(msg):
    try:
        yield
    except Exception, e:
        logger.warning(msg)
        logger.warning("Exception thrown: %s", e)

        continue_choice = 'C'
        abort_choice = 'A'
        opts = [continue_choice, abort_choice]
        prompt_str = "[C]ontinue the deploy or [A]bort?"
        user_opt = None
        while not user_opt in opts:
            user_opt = prompt(prompt_str)

        if user_opt == abort_choice:
            logger.critical("Aborting deploy")
            exit(1)
        logger.warning("Continuing, despite error")


@contextmanager
def logs_duration(deploy_timers, timer_name='Total', output_result=False):
    """
    A decorator to output the duration of the function after completion.
    """
    start_time = datetime.now()
    try:
        yield
    finally:
        duration = datetime.now() - start_time
        deploy_timers[timer_name] = duration.seconds
        if output_result:
            time_logger.info("%02ds- %s", duration.seconds, timer_name)
