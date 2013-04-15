"""
Base interface for a provisioner.
"""
import logging
import time

from fabric.api import prompt, env

logger = logging.getLogger('prov:base')
logger.setLevel(logging.INFO)


class BaseProvisioner(object):
    services = []

    def __init__(self, node, conf, *args, **kwargs):
        self.node = node
        self.conf = conf

    def start_services(self):
        """
        Start services that should be stopped during initial provisioning.
        """
        pass

    def stop_services(self):
        """
        Stop the services started by ``self.start_services``.
        """
        pass

    def fix_folder_perms(self):
        """
        Fix folder permissions that can break while restoring.
        """
        pass

    def do_first_launch_config(self):
        pass

    def do_update(self, first_run=False):
        pass

    def wait_for_condition(
        self, is_complete, waiting_message, retry_action=None, wait_seconds=5,
        prompt_cycles=None):
        """
        Wait for a condition to be true while giving the user good feedback on
        progress. Optionally prompt the user every `prompt_cycles` to:
            * Continue (keep waiting)
            * Skip (stop waiting and move on)
            * Abort (stop the entire deploy)

        `is_complete` A callable that returns True if we should stop
        `waiting_message` Message to display before waiting. Can be a template
          accepting `wait_seconds` as a variable.
        `retry_action` An optional function to call before waiting.
        `wait_seconds` Number of seconds to wait between retries
        `prompt_cycles` Optionally, prompt the user ever this many cycles to
          Continue/Skip/Abort this wait.
        """
        if retry_action is not None:
            assert callable(retry_action)

        opts = ['C', 'S', 'A']
        prompt_str = (
            "[C]ontinue waiting, "
            "[S]kip this check and move on with the deploy "
            "or [A]bort this deploy?"
        )
        cycles = 0
        while not is_complete():
            cycles += 1
            if retry_action:
                retry_action()
            logger.info(waiting_message, {'wait_seconds': wait_seconds})
            time.sleep(wait_seconds)
            if prompt_cycles and cycles % prompt_cycles == 0:
                user_opt = None
                while not user_opt in opts:
                    logger.warning(
                        "Manual intervention may be required: %s",
                        env.host_string,
                    )
                    user_opt = prompt(prompt_str)
                cycles = 0
                if user_opt == opts[0]:
                    # Continue
                    continue
                elif user_opt == opts[1]:
                    # Skip
                    logger.warning("Skipping this check")
                    return
                elif user_opt == opts[2]:
                    # Abort
                    logger.critical("Aborting deployment")
                    exit(1)

    @staticmethod
    def order_nodes_by_same_az(all_nodes, same_az_nodes):
        """
        Take a list of nodes and return that list with the `same_az_nodes`
        sorted to the front. This is useful for a case when you'd like a node
        to have affinity for a service located in its same AZ.
        """
        ordered_nodes = []
        ordered_nodes.extend(same_az_nodes)
        for node in all_nodes:
            if node not in same_az_nodes:
                ordered_nodes.append(node)

        return ordered_nodes
