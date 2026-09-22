import xarray as xr

from zen_garden.model.component_types.constraint import GenericConstraint


class CarbonEmissionsCumulativeConstraint(GenericConstraint):
    @classmethod
    def build(cls, model_constructor):
        """Summary:
        Cumulative carbon emissions over time.

        Formulation:

        .. math::
            \\text{First planning period } y = y_0, \\quad
            M_y^{\\mathrm{cum}} = m_0^{\\mathrm{cum}}+M_y
        .. math::
            \\text{Subsequent periods } y > y_0, \\quad M_y^{\\mathrm{cum}}
            = M_{y-1}^{\\mathrm{cum}} + (\\Delta y-1)M_{y-1}+M_y

        Notation:

        :math:`\\Delta y`: interval between planning periods
        :math:`M_y`: annual carbon emissions in year :math:`y`
        :math:`M_y^{\\mathrm{cum}}`: cumulative carbon emissions in year :math:`y`
        :math:`m_0^{\\mathrm{cum}}`: cumulative emissions before the modeled horizon
        """
        m = [
            True if year == model_constructor.model_schema.set_years[0] else False
            for year in model_constructor.model_schema.set_years
        ]

        cumulative = model_constructor.optimization_model.variables[
            "carbon_emissions_cumulative"
        ]
        annual = model_constructor.optimization_model.variables[
            "carbon_emissions_annual"
        ]
        tree = model_constructor.model_schema.scenario_tree
        if tree is None:
            cumulative_previous = cumulative.shift(set_years=1)
            annual_previous = annual.shift(set_years=1)
        else:
            nodes = model_constructor.model_schema.set_years
            parent_ids = xr.DataArray(
                [
                    tree.parent(node) if tree.parent(node) is not None else node
                    for node in nodes
                ],
                coords={"set_years": nodes},
                dims="set_years",
            )
            has_parent = xr.DataArray(
                [tree.parent(node) is not None for node in nodes],
                coords={"set_years": nodes},
                dims="set_years",
            )
            cumulative_previous = (
                cumulative.sel(set_years=parent_ids)
                .assign_coords(set_years=nodes)
                .where(has_parent)
            )
            annual_previous = (
                annual.sel(set_years=parent_ids)
                .assign_coords(set_years=nodes)
                .where(has_parent)
            )
        lhs = (
            cumulative
            - cumulative_previous
            - annual_previous
            * (model_constructor.config.system.interval_between_years - 1)
            - annual
        )
        cumulative_existing = (
            model_constructor.optimization_model.parameters.carbon_emissions_cumulative_existing
        )
        rhs = (
            xr.ones_like(
                model_constructor.optimization_model.variables[
                    "carbon_emissions_cumulative"
                ].mask
            )
            * cumulative_existing
        ).where(m, 0)
        constraints = lhs == rhs

        model_constructor.optimization_model.add_constraint(
            "constraint_carbon_emissions_cumulative", constraints
        )
