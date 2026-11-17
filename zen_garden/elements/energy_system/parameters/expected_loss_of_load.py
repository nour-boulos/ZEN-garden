"""Unserved-demand threshold used by the original FDM formulation."""

from zen_garden.elements.energy_system.parameters.probability import Probability


class ExpectedLossOfLoad(Probability):
    """Scalar threshold for FDM's probability-weighted shedding ratio."""

    name = "expected_loss_of_load"
    indices = ()
    doc = "Threshold for the original FDM expected loss of load constraint"
    unit_category = {}
    set_time_steps = None
