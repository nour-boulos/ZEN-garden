"""The original FDM expected-loss-of-load equation in the v3 constraint API."""

from zen_garden.model.component_types.constraint import GenericConstraint


class ExpectedLossOfLoadConstraint(GenericConstraint):
    """Retain FDM's probability weighting and its original factor of 0.5."""

    @classmethod
    def build(cls, model_constructor):
        if not model_constructor.config.system.use_stochastic_fdm:
            return
        model = model_constructor.optimization_model
        duration = cls.get_year_time_step_duration_array(model_constructor)
        demand = (model.parameters.demand * duration).sum(
            ["set_nodes", "set_time_steps_operation"]
        )
        shedding = (model.variables["shed_demand"] * duration).sum(
            ["set_nodes", "set_time_steps_operation"]
        )
        lhs = (
            (shedding * model.parameters.probability * 0.5 / demand)
            .where(demand > 0)
            .sum(["set_carriers", "set_years"])
        )
        model.add_constraint(
            "constraint_expected_loss_of_load",
            lhs <= model.parameters.expected_loss_of_load,
        )
