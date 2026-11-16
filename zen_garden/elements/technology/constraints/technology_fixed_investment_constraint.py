"""Equalities for fixed investments supplied through dataset inputs."""

from zen_garden.model.component_types.constraint import GenericConstraint


class TechnologyFixedInvestmentConstraint(GenericConstraint):
    """Fix power and storage-energy investment decisions to supplied values."""

    @classmethod
    def build(cls, model_constructor):
        system = model_constructor.config.system
        if system.allow_investment:
            return
        optimization_model = model_constructor.optimization_model
        investment = optimization_model.variables["capacity_investment"]
        fixed_power = optimization_model.parameters.capacity_investment_fixed
        optimization_model.add_constraint(
            "constraint_capacity_investment_fixed_power",
            investment.sel(set_capacity_types="power") == fixed_power,
        )

        storage = optimization_model.sets["set_storage_technologies"]
        if not storage:
            return
        fixed_energy = optimization_model.parameters.capacity_investment_fixed_energy
        fixed_energy = fixed_energy.rename(
            {
                "set_storage_technologies": "set_technologies",
                "set_nodes": "set_location",
            }
        )
        optimization_model.add_constraint(
            "constraint_capacity_investment_fixed_energy",
            investment.sel(set_capacity_types="energy", set_technologies=storage)
            == fixed_energy,
        )
