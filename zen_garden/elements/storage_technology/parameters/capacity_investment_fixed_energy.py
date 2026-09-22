"""Storage energy-capacity investments for an explicit replay run."""

from zen_garden.model.component_types.parameter import GenericParameter


class CapacityInvestmentFixedEnergy(GenericParameter):
    """Fixed energy investment, loaded only in fixed-replay mode."""

    name = "capacity_investment_fixed_energy"
    indices = ("set_storage_technologies", "set_nodes", "set_years")
    doc = "Prescribed storage energy-capacity investment"
    unit_category = {"energy_quantity": 1}
    fixed_replay_only = True

    @classmethod
    def store_input_data(cls, element):
        policy = element.model_schema.fixed_investments
        if policy is None:
            raise ValueError("Fixed-investment policy was not loaded")
        element.capacity_investment_fixed_energy = policy.for_element(element, "energy")
        element.units[cls.name] = element.units["capacity_existing_energy"]
