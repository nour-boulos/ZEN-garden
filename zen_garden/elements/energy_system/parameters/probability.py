"""Operating-future probabilities for the fictitious-year FDM mode."""

from zen_garden.model.component_types.parameter import GenericParameter


class Probability(GenericParameter):
    """Probability assigned to each fictitious operating-year slot."""

    name = "probability"
    indices = ("set_years",)
    doc = "Probability of the operating future represented by a fictitious year"
    unit_category = {}
    set_time_steps = "set_years"

    @classmethod
    def store_input_data(cls, element):
        """Read probabilities only when FDM mode is enabled."""
        if element.config.system.use_stochastic_fdm:
            super().store_input_data(element)

    @classmethod
    def build(cls, model_constructor):
        """Keep ordinary datasets independent of FDM probability inputs."""
        if model_constructor.config.system.use_stochastic_fdm:
            super().build(model_constructor)
