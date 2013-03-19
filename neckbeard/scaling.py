
from abc import ABCMeta, abstractmethod


class ScalingBackend:
    __metaclass__ = ABCMeta

    @abstractmethod
    def get_indexes_for_resource(
        self,
        environment,
        resource_type,
        resource_name,
        resource_configuration,
    ):
        """
        For the given name and type of resource, output a range to indicate how
        many of the resource should exist and what their `scaling_index` should
        be. A `ScalingBackend` might do things like check load metrics to
        determine the desired scale, or it might have stored a configuration
        somewhere shared to allow changing this value.

        For example, if a backend determines that 4 resources of this
        name/type should exist and they should be sequentially indexed, it
        would return:

            range(4)
        """
        return []

    def get_maximum_scale(self, resource_configuration):
        scaling = resource_configuration.get('scaling', {})
        return scaling.get('maximum', 1)

    def get_minimum_scale(self, resource_configuration):
        scaling = resource_configuration.get('scaling', {})
        return scaling.get('minimum', 1)


class MaxScalingBackend(ScalingBackend):
    """
    A scaling manager that always assumes the *maximum* allowed number of nodes
    is the current scale.
    """
    def get_indexes_for_resource(
        self,
        environment,
        resource_type,
        resource_name,
        resource_configuration,
    ):
        return range(self.get_maximum_scale(resource_configuration))


class MinScalingBackend(ScalingBackend):
    """
    A scaling manager that always assumes the *minimum* allowed number of nodes
    is the current scale.
    """
    def get_indexes_for_resource(
        self,
        environment,
        resource_type,
        resource_name,
        resource_configuration,
    ):
        return range(self.get_minimum_scale(resource_configuration))
