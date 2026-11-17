import numpy as np

from zen_garden.model.component_types.constraint import GenericConstraint


class TechnologyMaxCapacityAdditionConstraint(GenericConstraint):
    @classmethod
    def build(cls, model_constructor):
        """Summary:
        Max capacity addition of technology.

        Formulation:

        .. math::
            \\overline{\\Delta k}_{h} g_{h,p,y}
            \\geq \\Delta K_{h,p,y}

        FDM mode uses the original FDM direct addition bound, including zeros.
        Ordinary mode retains its installation-binary bound and skips zeros.

        Notation:

        :math:`\\overline{\\Delta k}_{h}`: maximum capacity addition for technology
        :math:`h` (with capacity type implicit)
        :math:`g_{h,p,y}`: binary variable which equals 1 if technology is installed
        at location :math:`p` in year :math:`y`
        :math:`\\Delta K_{h,p,y}`: capacity addition
        """
        system = model_constructor.config.system
        if not system.allow_investment:
            return

        model = model_constructor.optimization_model
        maximum = model.parameters.capacity_addition_max
        addition = model.variables["capacity_addition"]
        finite = maximum.notnull() & (maximum != np.inf)

        if not system.use_stochastic_fdm:
            mask = finite & (maximum != 0)
            if not mask.any():
                return
            installation = model.variables["technology_installation"]
            lhs = addition - maximum.where(mask, 0) * installation
            model.add_constraint(
                "constraint_technology_max_capacity_addition", lhs.where(mask) <= 0
            )
            return

        if not finite.any():
            return
        model.add_constraint(
            "constraint_technology_max_capacity_addition",
            addition.where(finite) <= maximum.where(finite, 0),
        )
