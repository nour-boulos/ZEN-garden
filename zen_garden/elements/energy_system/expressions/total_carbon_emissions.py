import xarray as xr

from zen_garden.model.component_types.expression import GenericExpression


class TotalCarbonEmissions(GenericExpression):
    """Total carbon emissions objective expression.

    .. math::
        J = E^{\\mathrm{cum}}_Y

    :math:`E^{\\mathrm{cum}}_Y`: cumulative carbon emissions at the end of the
    time horizon.
    """

    name = "total_carbon_emissions"
    doc = "Cumulative carbon emissions at the end of the time horizon"

    @classmethod
    def get_expression(cls, model_constructor):
        optimization_model = model_constructor.optimization_model
        tree = model_constructor.model_schema.scenario_tree
        if tree is not None:
            leaves = list(tree.leaves)
            weights = xr.DataArray(
                [tree.probability(node) for node in leaves],
                coords={"set_years": leaves},
                dims="set_years",
            )
            cumulative = optimization_model.variables[
                "carbon_emissions_cumulative"
            ].sel(set_years=leaves)
            return (cumulative * weights).sum("set_years")
        return (
            optimization_model.variables["carbon_emissions_cumulative"]
            .at[optimization_model.sets["set_years"][-1]]
            .to_linexpr()
        )
