"""Check shared annual CAPEX accounting and the retained FDM constraints."""

from pathlib import Path
from shutil import copytree
from types import SimpleNamespace

import linopy as lp
import numpy as np
import pandas as pd
import pytest
import xarray as xr
import yaml

from zen_garden.config import Config
from zen_garden.elements.energy_system.constraints import (
    CostTotalConstraint,
    ExpectedLossOfLoadConstraint,
    NetPresentCostConstraint,
)
from zen_garden.elements.energy_system.expressions.total_cost import TotalCost
from zen_garden.elements.technology.constraints import (
    TechnologyMaxCapacityAdditionConstraint,
)
from zen_garden.model.schema import ModelSchema
from zen_garden.workflow.optimization_step import OptimizationStep
from zen_garden.workflow.optimization_workflow import OptimizationWorkflow


def indexed(values, **coordinates):
    return xr.DataArray(values, coords=coordinates, dims=list(coordinates))


def component_context(tmp_path, fdm=True):
    config = Config()
    config.system.use_stochastic_fdm = fdm
    config.system.optimized_years = 2
    model = SimpleNamespace(
        lp_model=lp.Model(solver_dir=tmp_path),
        parameters=SimpleNamespace(discount_rate=0.0),
        sets={"set_years": [0, 1]},
    )
    model.variables = model.lp_model.variables
    model.add_constraint = lambda name, constraint: model.lp_model.add_constraints(
        constraint, name=name
    )
    return SimpleNamespace(
        config=config,
        optimization_model=model,
        model_schema=SimpleNamespace(
            set_years=[0, 1], set_years_entire_horizon=[0, 1], scenario_tree=None
        ),
    )


@pytest.mark.parametrize(
    ("fdm", "high_probability", "expected_capacity", "expected_cost"),
    [(True, 0.5, 100, 270), (True, 0.8, 100, 288), (False, 0.5, 100, 540)],
)
def test_shared_investment_cost_equations(
    tmp_path, fdm, high_probability, expected_capacity, expected_cost
):
    """Compare the ported cost/bound equations with independent hand optima."""
    context = component_context(tmp_path, fdm)
    model = context.optimization_model
    native = model.lp_model
    capacity_coords = [
        pd.Index(["pipeline", "truck"], name="set_technologies"),
        pd.Index(["power"], name="set_capacity_types"),
        pd.Index(["route"], name="set_location"),
        pd.Index([0, 1], name="set_years"),
    ]
    addition = native.add_variables(0, coords=capacity_coords, name="capacity_addition")
    if not fdm:
        native.add_variables(
            coords=capacity_coords, binary=True, name="technology_installation"
        )
    model.parameters.capacity_addition_max = indexed(
        [[[100.0, 0.0]], [[100.0, 0.0]]],
        set_technologies=["pipeline", "truck"],
        set_capacity_types=["power"],
        set_years=[0, 1],
    )
    TechnologyMaxCapacityAdditionConstraint.build(context)
    flow = native.add_variables(
        0,
        coords=[capacity_coords[0], capacity_coords[-1]],
        name="flow",
    )
    native.add_constraints(
        flow
        <= addition.sel(set_capacity_types="power", set_location="route", set_years=0)
    )
    native.add_constraints(
        flow.sum("set_technologies") == indexed([40, 100], set_years=[0, 1])
    )
    costs = {}
    for name in (
        "cost_total",
        "net_present_cost",
        "cost_capex_yearly_total",
        "cost_opex_yearly_total",
        "cost_carrier_total",
        "cost_carbon_emissions_total",
    ):
        costs[name] = native.add_variables(coords=[capacity_coords[-1]], name=name)
    for name in ("cost_carrier_total", "cost_carbon_emissions_total"):
        native.add_constraints(costs[name] == 0)
    investment = addition.sel(
        set_technologies="pipeline",
        set_capacity_types="power",
        set_location="route",
        set_years=0,
    )
    # Annual capital is 4*K/2 in every slot; FDM includes it once.
    native.add_constraints(costs["cost_capex_yearly_total"] == 4 * investment / 2)
    native.add_constraints(
        costs["cost_opex_yearly_total"]
        == flow.sel(set_technologies="pipeline")
        + 8 * flow.sel(set_technologies="truck")
    )
    model.parameters.probability = indexed(
        [1 - high_probability, high_probability], set_years=[0, 1]
    )
    CostTotalConstraint.build(context)
    NetPresentCostConstraint.build(context)
    native.add_objective(TotalCost.get_expression(context))
    status, condition = native.solve(solver_name="highs", sanitize_zeros=True)
    assert (status, condition) == ("ok", "optimal")
    chosen = native.variables["capacity_addition"].solution.sel(
        set_technologies="pipeline",
        set_capacity_types="power",
        set_location="route",
        set_years=0,
    )
    assert chosen.item() == pytest.approx(expected_capacity)
    assert native.objective.value == pytest.approx(expected_cost)
    if fdm:
        assert float(abs(addition.solution.sel(set_years=1)).max()) == 0


def test_fdm_direct_bound_keeps_original_binary_semantics(tmp_path):
    """FDM's upper bound deliberately contains no installation-binary term."""
    context = component_context(tmp_path)
    model = context.optimization_model
    native = model.lp_model
    years = pd.Index([0, 1], name="set_years")
    addition = native.add_variables(0, coords=[years], name="capacity_addition")
    installation = native.add_variables(
        binary=True, coords=[years], name="technology_installation"
    )
    model.parameters.capacity_addition_max = indexed([40, 0], set_years=[0, 1])
    TechnologyMaxCapacityAdditionConstraint.build(context)
    native.add_constraints(installation == 0)
    native.add_objective(-addition.sum())
    assert native.solve(solver_name="highs", sanitize_zeros=True) == ("ok", "optimal")
    assert addition.solution.values.tolist() == [40, 0]


@pytest.mark.parametrize("fdm", [False, True])
def test_running_cost_weights_and_discount_switch(tmp_path, fdm):
    """Exercise nonzero operating, carrier and carbon costs with unequal weights."""
    context = component_context(tmp_path, fdm)
    model = context.optimization_model
    native = model.lp_model
    years = pd.Index([0, 1], name="set_years")
    for name, values in (
        ("cost_capex_yearly_total", [8, 8]),
        ("cost_opex_yearly_total", [10, 30]),
        ("cost_carrier_total", [20, 50]),
        ("cost_carbon_emissions_total", [40, 70]),
    ):
        variable = native.add_variables(coords=[years], name=name)
        native.add_constraints(variable == indexed(values, set_years=[0, 1]))
    for name in ("cost_total", "net_present_cost"):
        native.add_variables(coords=[years], name=name)
    model.parameters.probability = indexed([0.25, 0.75], set_years=[0, 1])
    model.parameters.discount_rate = 0.1
    CostTotalConstraint.build(context)
    NetPresentCostConstraint.build(context)
    native.add_objective(TotalCost.get_expression(context))
    assert native.solve(solver_name="highs", sanitize_zeros=True) == ("ok", "optimal")
    assert native.objective.value == pytest.approx(138 if fdm else 78 + 158 / 1.1)
    assert native.variables["cost_capex_yearly_total"].solution.values == pytest.approx(
        [8, 8]
    )
    if fdm:
        assert native.variables["cost_total"].solution.values == pytest.approx(
            [8 + 0.25 * 70, 0.75 * 150]
        )


@pytest.mark.parametrize(
    ("years", "probabilities"),
    [([5], [1.0]), ([5, 9], [0.0, 1.0]), ([9, 5], [0.75, 0.25])],
)
def test_capital_uses_first_model_slot_and_keeps_annual_values(
    tmp_path, years, probabilities
):
    """The shared charge is independent of the first future's label or weight."""
    context = component_context(tmp_path)
    context.model_schema.set_years = years
    context.model_schema.set_years_entire_horizon = years
    model = context.optimization_model
    model.parameters.discount_rate = 0.05
    model.parameters.probability = indexed(probabilities, set_years=years)
    native = model.lp_model
    coords = [pd.Index(years, name="set_years")]
    for name in ("cost_total", "net_present_cost"):
        native.add_variables(coords=coords, name=name)
    for name, value in (
        ("cost_capex_yearly_total", 53.78),
        ("cost_opex_yearly_total", 20),
        ("cost_carrier_total", 0),
        ("cost_carbon_emissions_total", 0),
    ):
        variable = native.add_variables(coords=coords, name=name)
        native.add_constraints(variable == value)
    CostTotalConstraint.build(context)
    NetPresentCostConstraint.build(context)
    native.add_objective(TotalCost.get_expression(context))
    assert native.solve(solver_name="highs", sanitize_zeros=True) == ("ok", "optimal")
    assert native.objective.value == pytest.approx(73.78)
    assert native.variables["cost_capex_yearly_total"].solution.values == pytest.approx(
        [53.78] * len(years)
    )
    expected = [
        (53.78 if year == years[0] else 0) + probability * 20
        for year, probability in zip(years, probabilities, strict=True)
    ]
    assert native.variables["cost_total"].solution.values == pytest.approx(expected)


def test_two_future_hand_example_counts_capital_once(tmp_path):
    """The EUR 100, two-year, 5% example has annual total EUR 73.780488."""
    context = component_context(tmp_path)
    model = context.optimization_model
    model.parameters.discount_rate = 0.05
    model.parameters.probability = indexed([0.5, 0.5], set_years=[0, 1])
    native = model.lp_model
    coords = [pd.Index([0, 1], name="set_years")]
    annual_capital = 100 * 0.05 / (1 - 1.05**-2)
    for name, values in (
        ("cost_capex_yearly_total", [annual_capital, annual_capital]),
        ("cost_opex_yearly_total", [10, 30]),
        ("cost_carrier_total", [0, 0]),
        ("cost_carbon_emissions_total", [0, 0]),
    ):
        variable = native.add_variables(coords=coords, name=name)
        native.add_constraints(variable == indexed(values, set_years=[0, 1]))
    for name in ("cost_total", "net_present_cost"):
        native.add_variables(coords=coords, name=name)
    CostTotalConstraint.build(context)
    NetPresentCostConstraint.build(context)
    native.add_objective(TotalCost.get_expression(context))
    assert native.solve(solver_name="highs", sanitize_zeros=True) == ("ok", "optimal")
    assert native.objective.value == pytest.approx(73.78048780487802)
    assert float(native.variables["net_present_cost"].solution.sum()) == pytest.approx(
        native.objective.value
    )


def test_original_reliability_factor_and_zero_demand_mask(tmp_path):
    """The source's 0.5 factor permits ten units of shedding in this example."""
    context = component_context(tmp_path)
    model = context.optimization_model
    native = model.lp_model
    context.time_steps = SimpleNamespace(get_time_steps_year2operation=lambda y: [y])
    model.parameters.time_steps_operation_duration = indexed(
        [1, 1], set_time_steps_operation=[0, 1]
    )
    model.parameters.demand = indexed(
        [[[100, 100]], [[0, 0]]],
        set_carriers=["served", "zero_demand"],
        set_nodes=["node"],
        set_time_steps_operation=[0, 1],
    )
    model.parameters.probability = indexed([0.5, 0.5], set_years=[0, 1])
    model.parameters.expected_loss_of_load = 0.05
    shedding = native.add_variables(
        0,
        100,
        coords=[
            pd.Index(["served", "zero_demand"], name="set_carriers"),
            pd.Index(["node"], name="set_nodes"),
            pd.Index([0, 1], name="set_time_steps_operation"),
        ],
        name="shed_demand",
    )
    native.add_constraints(shedding.sel(set_carriers="zero_demand") == 0)
    native.add_constraints(
        shedding.sel(set_time_steps_operation=0)
        == shedding.sel(set_time_steps_operation=1)
    )
    ExpectedLossOfLoadConstraint.build(context)
    native.add_objective(-shedding.sum())
    assert native.solve(solver_name="highs", sanitize_zeros=True) == ("ok", "optimal")
    assert shedding.solution.sel(set_carriers="served").values.ravel() == pytest.approx(
        [10, 10]
    )


@pytest.mark.parametrize(("fdm", "min_load"), [(False, 0), (True, 0), (True, 0.1)])
def test_native_input_loading_and_solve(tmp_path, fdm, min_load):
    """Use a temporary existing gas/heat case to exercise all v3 services."""
    source = Path(__file__).parents[2] / "testcases/test_1c"
    dataset = tmp_path / "native_case"
    copytree(source, dataset)
    system_path = dataset / "system.yaml"
    system = yaml.safe_load(system_path.read_text())
    if fdm:
        system.update(
            use_stochastic_fdm=True, optimized_years=2, total_hours_per_year=1
        )
        energy_path = dataset / "energy_system/attributes.yaml"
        energy = yaml.safe_load(energy_path.read_text())
        energy["discount_rate"]["default_value"] = 0.0
        energy["carbon_emissions_budget"]["default_value"] = float("inf")
        energy["probability"] = {"default_value": 0.5, "unit": "1"}
        energy["expected_loss_of_load"] = {"default_value": 0.0, "unit": "1"}
        energy_path.write_text(yaml.safe_dump(energy))
        for folder in (dataset / "set_technologies").glob("*/*"):
            attributes = folder / "attributes.yaml"
            if not attributes.exists():
                continue
            data = yaml.safe_load(attributes.read_text())
            data["lifetime"]["default_value"] = 2.0
            if folder.name == "natural_gas_boiler":
                data["min_load"]["default_value"] = min_load
            attributes.write_text(yaml.safe_dump(data))
            (folder / "capacity_addition_max.csv").write_text(
                "year,capacity_addition_max\n2022,1000\n2023,0\n"
            )
    system_path.write_text(yaml.safe_dump(system))
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"solver": {"name": "highs"}}))
    config = Config.from_file(config_path, dataset_path=dataset, folder_output=tmp_path)
    config.validate_configurations()
    workflow = OptimizationWorkflow(ModelSchema(config), {})
    workflow.load_data()
    workflow.aggregate_time_series()
    years = workflow.model_schema.set_years
    step = workflow.service_container.build(
        OptimizationStep, optimized_time_steps=[0], steps_horizon={0: years}
    )
    model = step.construct_optimization_problem()
    step.solve("")
    assert step.optimality
    assert model.parameters.capacity_addition_max.dims == (
        "set_technologies",
        "set_capacity_types",
        "set_years",
    )
    if fdm:
        assert model.parameters.probability.values.tolist() == [0.5, 0.5]
        assert model.parameters.expected_loss_of_load == 0
        assert (
            float(
                abs(
                    model.variables["capacity_investment"].solution.sel(set_years=1)
                ).max()
            )
            == 0
        )
    else:
        assert not hasattr(model.parameters, "probability")
    model.lp_model.to_file(tmp_path / "solved_model.lp")
    for name in model.lp_model.constraints:
        constraint = model.lp_model.constraints[name]
        assert not ((constraint.vars >= 0) & ~np.isfinite(constraint.coeffs)).any()
