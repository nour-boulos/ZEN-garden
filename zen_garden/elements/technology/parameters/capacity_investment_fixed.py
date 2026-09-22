"""Power-capacity investments prescribed for an explicit replay run."""

from zen_garden.model.component_types.parameter import GenericParameter


class CapacityInvestmentFixed(GenericParameter):
    """Fixed power investment, loaded only in fixed-replay mode."""

    name = "capacity_investment_fixed"
    indices = ("set_technologies", "set_location", "set_years")
    doc = "Prescribed technology power-capacity investment"
    unit_category = {"energy_quantity": 1, "time": -1}
    fixed_replay_only = True

    @classmethod
    def store_input_data(cls, element):
        policy = element.model_schema.fixed_investments
        if policy is None:
            raise ValueError("Fixed-investment policy was not loaded")
        element.capacity_investment_fixed = policy.for_element(element, "power")
        element.units[cls.name] = element.units["capacity_existing"]
