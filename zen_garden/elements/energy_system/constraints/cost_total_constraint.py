from zen_garden.model.component_types.constraint import GenericConstraint


class CostTotalConstraint(GenericConstraint):
    @classmethod
    def build(cls, model_constructor):
        """Summary:
        Add up all costs from technologies and carriers.

        Formulation:

        .. math::
            C^{\\mathrm{total}}_y = C^{\\mathrm{cap}}_y + C^{\\mathrm{op}}_y +
            C^{\\mathrm{carrier}}_y + C^{\\mathrm{CO_2}}_y

        Notation:

        :math:`C^{\\mathrm{total}}_y`: total cost of energy system in year :math:`y`
        :math:`C^{\\mathrm{cap}}_y`: annual capital expenditures in year :math:`y`
        :math:`C^{\\mathrm{op}}_y`: annual operational expenditures for operating
        technologies in year :math:`y`
        :math:`C^{\\mathrm{carrier}}_y`: annual operational expenditures for for
        importing and exporting carriers in year :math:`y`
        :math:`C^{\\mathrm{CO_2}}_y`: annual operational expenditures for carbon
        emissions in year :math:`y`
        """
        model = model_constructor.optimization_model
        weight = (
            model.parameters.probability
            if model_constructor.config.system.use_stochastic_fdm
            else 1
        )
        running_cost = (
            model.variables["cost_opex_yearly_total"]
            + model.variables["cost_carrier_total"]
            + model.variables["cost_carbon_emissions_total"]
        )
        lhs = (
            model.variables["cost_total"]
            - model.variables["cost_capex_yearly_total"]
            - weight * running_cost
        )
        rhs = 0
        constraints = lhs == rhs

        model_constructor.optimization_model.add_constraint(
            "constraint_cost_total", constraints
        )
