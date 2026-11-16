"""Storage energy-capacity investments prescribed through the dataset."""

from zen_garden.model.component_types.parameter import GenericParameter


class CapacityInvestmentFixedEnergy(GenericParameter):
    """Fixed storage-energy investment when optimization is disabled."""

    name = "capacity_investment_fixed_energy"
    indices = ("set_storage_technologies", "set_nodes", "set_years")
    doc = "Prescribed storage energy-capacity investment"
    unit_category = {"energy_quantity": 1}
    fixed_replay_only = True
