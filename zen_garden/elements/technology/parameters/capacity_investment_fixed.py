"""Power-capacity investments prescribed through the dataset."""

from zen_garden.model.component_types.parameter import GenericParameter


class CapacityInvestmentFixed(GenericParameter):
    """Fixed power investment used when investment optimization is disabled."""

    name = "capacity_investment_fixed"
    indices = ("set_technologies", "set_location", "set_years")
    doc = "Prescribed technology power-capacity investment"
    unit_category = {"energy_quantity": 1, "time": -1}
    fixed_replay_only = True
