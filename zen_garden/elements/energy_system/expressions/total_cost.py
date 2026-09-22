import xarray as xr

from zen_garden.model.component_types.expression import GenericExpression


class TotalCost(GenericExpression):
    """Total net present cost objective expression.

    .. math::
        J = \\sum_{y\\in\\mathcal{Y}} NPC_y
    """

    name = "total_cost"
    doc = "Total net present cost, summed over all modeled years"

    @classmethod
    def get_expression(cls, model_constructor):
        cost = model_constructor.optimization_model.variables["net_present_cost"]
        tree = model_constructor.model_schema.scenario_tree
        if tree is None:
            return cost.sum("set_years")
        nodes = model_constructor.model_schema.set_years
        weights = xr.DataArray(
            [tree.probability(node) for node in nodes],
            coords={"set_years": nodes},
            dims="set_years",
        )
        return (cost * weights).sum("set_years")
