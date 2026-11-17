"""Build a small CCS investment MILP with economies of scale and audit native solves.

The runner never adds constraints, changes variable bounds, or alters the native
objective. Exit 1 records an intended-design acceptance failure, not necessarily
a solver failure. All generated inputs and complete results are saved locally.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import itertools
import json
import logging
import math
import subprocess
import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from data.fdm_ccs_binary_test import build_dataset as base
from data.fdm_ccs_binary_test.run_checks import dump_array, equation_terms, scalar
from zen_garden.config import Config
from zen_garden.model.schema import ModelSchema
from zen_garden.workflow.optimization_step import OptimizationStep
from zen_garden.workflow.optimization_workflow import OptimizationWorkflow

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent.parent
OUT = PROJECT / "checkpoints/stochastic_fixed_investment/21_binary_capacity_link_repair"
HOURS = 8760
RATE = 0.05
LIFETIME = 50
ANNUITY = RATE / (1 - (1 + RATE) ** -LIFETIME)
SIZES = {"pipeline_small": 60.0, "pipeline_large": 100.0}
BUILD_COST = {"pipeline_small": 1200.0, "pipeline_large": 1600.0}
CASES = {
    "stochastic_equal": {"demand": [40.0, 100.0], "probability": [0.5, 0.5]},
    "stochastic_rare_high": {"demand": [40.0, 100.0], "probability": [0.95, 0.05]},
    "stochastic_equal_duplicated": {
        "demand": [40.0, 100.0, 40.0, 100.0],
        "probability": [0.25, 0.25, 0.25, 0.25],
    },
    "deterministic_low": {"demand": [40.0], "probability": [1.0]},
    "deterministic_high": {"demand": [100.0], "probability": [1.0]},
}
EXPECTED_FUTURE_CONTROLS = {
    "deterministic_expected_equal": "stochastic_equal",
    "deterministic_expected_rare_high": "stochastic_rare_high",
}
for control, stochastic in EXPECTED_FUTURE_CONTROLS.items():
    futures = CASES[stochastic]
    mean_demand = sum(
        d * p for d, p in zip(futures["demand"], futures["probability"], strict=True)
    )
    CASES[control] = {"demand": [mean_demand], "probability": [1.0]}
CHECKS = []


def check(case, category, name, actual, expected, passed):
    CHECKS.append(
        {
            "case": case,
            "category": category,
            "check": name,
            "actual": str(actual),
            "expected": str(expected),
            "passed": bool(passed),
        }
    )


def near(case, category, name, actual, expected):
    check(
        case,
        category,
        name,
        actual,
        expected,
        math.isclose(float(actual), float(expected), rel_tol=1e-7, abs_tol=1e-7),
    )


def source_hashes():
    return {
        str(p.relative_to(PROJECT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((PROJECT / "zen_garden").rglob("*.py"))
    }


def build_inputs(name, specification):
    folder = ROOT / "cases" / name
    if folder.exists():
        return folder
    previous_root = base.ROOT
    base.ROOT = ROOT
    try:
        base.build_case(
            name, {"kind": "fixed_cost", "probabilities": specification["probability"]}
        )
    finally:
        base.ROOT = previous_root
    energy_path = folder / "energy_system/attributes.yaml"
    energy = yaml.safe_load(energy_path.read_text())
    energy["discount_rate"]["default_value"] = RATE
    base.write_yaml(energy_path, energy)
    for path in folder.glob("set_technologies/*/*/attributes.yaml"):
        attributes = yaml.safe_load(path.read_text())
        attributes["lifetime"]["default_value"] = LIFETIME
        attributes["depreciation_time"]["default_value"] = LIFETIME
        if path.parent.name in BUILD_COST:
            attributes["capex_per_distance_transport"]["default_value"] = BUILD_COST[
                path.parent.name
            ]
        base.write_yaml(path, attributes)
    demand_folder = folder / "set_carriers/captured_carbon"
    first_demand = specification["demand"][0]
    base.write_csv(
        demand_folder / "demand.csv",
        [
            {"node": node, "demand": first_demand / HOURS if node == "sink" else 0.0}
            for node in ("source", "sink")
        ],
    )
    if len(specification["demand"]) > 1:
        base.write_csv(
            demand_folder / "demand_yearly_variation.csv",
            [
                {
                    "node": node,
                    "year": 2026 + slot,
                    "demand_yearly_variation": demand / first_demand,
                }
                for node in ("source", "sink")
                for slot, demand in enumerate(specification["demand"])
            ],
        )
    return folder


def hand_calculations():
    rows = []
    expected = {}
    for name, specification in CASES.items():
        candidates = []
        for choices in itertools.product((0, 1), repeat=2):
            builds = dict(zip(SIZES, choices, strict=True))
            capacity = sum(SIZES[t] * builds[t] for t in SIZES)
            upfront = sum(BUILD_COST[t] * builds[t] for t in SIZES)
            operating = [
                min(d, capacity) + 8 * max(d - capacity, 0)
                for d in specification["demand"]
            ]
            expected_operation = sum(
                p * c
                for p, c in zip(specification["probability"], operating, strict=True)
            )
            row = {
                "case": name,
                **builds,
                "capacity_tonnes_per_year": capacity,
                "upfront_EUR": upfront,
                "annual_capital_EUR": ANNUITY * upfront,
                "expected_operation_EUR": expected_operation,
                "annual_total_EUR": ANNUITY * upfront + expected_operation,
                "operation_by_future_EUR": json.dumps(operating),
            }
            rows.append(row)
            candidates.append(row)
        best = min(candidates, key=lambda row: row["annual_total_EUR"])
        expected[name] = {**specification, "best": best}
    base.write_csv(ROOT / "hand_calculations/all_build_choices.csv", rows)
    (ROOT / "hand_calculations/expected.json").write_text(
        json.dumps(expected, indent=2) + "\n"
    )
    return expected


def coefficient(constraint, variable, key):
    selected = {k: v for k, v in key.items() if k in constraint.vars.dims}
    labels = constraint.vars.sel(selected).values.ravel()
    values = constraint.coeffs.sel(selected).values.ravel()
    target = int(variable)
    return float(values[(labels == target) & np.isfinite(values)].sum())


def run_case(name, specification):
    dataset = ROOT / "cases" / name
    folder = OUT / name
    folder.mkdir(parents=True, exist_ok=True)
    config = Config.from_file(
        dataset / "config.yaml",
        dataset_path=dataset,
        folder_output=folder / "native_output",
    )
    config.validate_configurations()
    workflow = OptimizationWorkflow(ModelSchema(config), {})
    workflow.load_data()
    workflow.aggregate_time_series()
    years = workflow.model_schema.set_years
    step = workflow.service_container.build(
        OptimizationStep, optimized_time_steps=[0], steps_horizon={0: years}
    )
    model = step.construct_optimization_problem()
    native = model.lp_model
    p = model.parameters
    fdm = len(years) > 1
    check(
        name,
        "input",
        "FDM setting",
        config.system.use_stochastic_fdm,
        fdm,
        config.system.use_stochastic_fdm == fdm,
    )
    near(name, "input", "discount rate", p.discount_rate, RATE)
    check(
        name,
        "input",
        "physical lifetimes unchanged",
        p.lifetime.values,
        LIFETIME,
        np.allclose(p.lifetime, LIFETIME),
    )
    check(
        name,
        "input",
        "financial lifetimes unchanged",
        p.depreciation_time.values,
        LIFETIME,
        np.allclose(p.depreciation_time, LIFETIME),
    )
    near(
        name,
        "input",
        "free capture capex",
        float(abs(p.capex_specific_conversion).max()),
        0,
    )
    near(
        name,
        "input",
        "free capture operation",
        float(abs(p.opex_specific_variable.sel(set_technologies="capture")).max()),
        0,
    )
    near(name, "input", "capture ratio", float(p.conversion_factor.min()), 1)
    check(
        name,
        "input",
        "shedding prohibited",
        p.price_shed_demand.values,
        "+inf",
        np.isposinf(p.price_shed_demand).all(),
    )
    near(
        name,
        "input",
        "no captured carbon imports",
        float(abs(p.availability_import.sel(set_carriers="captured_carbon")).max()),
        0,
    )
    if fdm:
        check(
            name,
            "input",
            "probability vector",
            p.probability.values,
            specification["probability"],
            np.allclose(p.probability, specification["probability"]),
        )
        near(name, "input", "probability sum", float(p.probability.sum()), 1)
        near(name, "input", "no loss of load", p.expected_loss_of_load, 0)
    annual_rows = []
    for slot, (demand, probability) in enumerate(
        zip(specification["demand"], specification["probability"], strict=True)
    ):
        times = step.time_steps.get_time_steps_year2operation(slot)
        duration = p.time_steps_operation_duration.sel(set_time_steps_operation=times)
        actual = float(
            (
                p.demand.sel(
                    set_carriers="captured_carbon",
                    set_nodes="sink",
                    set_time_steps_operation=times,
                )
                * duration
            ).sum()
        )
        near(name, "input", f"slot {slot} annual demand", actual, demand)
        near(name, "input", f"slot {slot} hours", float(duration.sum()), HOURS)
        annual_rows.append(
            {"slot": slot, "demand_tonnes": actual, "probability": probability}
        )
    for technology, size in SIZES.items():
        key = {"set_technologies": technology, "set_capacity_types": "power"}
        near(
            name,
            "input",
            f"{technology} minimum size",
            float(p.capacity_addition_min.sel(key)) * HOURS,
            size,
        )
        near(
            name,
            "input",
            f"{technology} first maximum size",
            float(p.capacity_addition_max.sel(**key, set_years=0)) * HOURS,
            size,
        )
        near(
            name,
            "input",
            f"{technology} no linear capex",
            float(
                abs(
                    p.capex_specific_transport.sel(
                        set_transport_technologies=technology
                    )
                ).max()
            ),
            0,
        )
        near(
            name,
            "input",
            f"{technology} fixed upfront fee",
            float(
                p.transport_capex_distance.sel(
                    set_transport_technologies=technology,
                    set_edges="source-sink",
                    set_years=0,
                )
            ),
            BUILD_COST[technology],
        )
    if fdm:
        near(
            name,
            "input",
            "all later addition limits zero",
            float(abs(p.capacity_addition_max.sel(set_years=years[1:])).max()),
            0,
        )
    for parameter in (
        "probability",
        "discount_rate",
        "capacity_addition_min",
        "capacity_addition_max",
        "capex_specific_transport",
        "transport_capex_distance",
        "distance",
        "lifetime",
        "depreciation_time",
    ):
        if hasattr(p, parameter):
            dump_array(getattr(p, parameter), folder / f"loaded_{parameter}.csv")
    assert all(
        r["passed"] for r in CHECKS if r["case"] == name and r["category"] == "input"
    ), "Input audit failed"
    installation = native.variables["technology_installation"]
    binary_count = int((installation.labels >= 0).sum())
    check(
        name,
        "MILP",
        "installation variables declared binary",
        installation.attrs,
        True,
        bool(installation.attrs.get("binary", False)),
    )
    near(name, "MILP", "number of build binaries", binary_count, 2 * len(years))
    step.solve("")
    check(
        name,
        "solver",
        "optimal",
        native.termination_condition,
        "optimal",
        step.optimality and native.termination_condition == "optimal",
    )
    assert step.optimality
    native.to_file(folder / "solved_model.lp")
    native.solution.to_netcdf(folder / "solution.nc")
    equation_terms(model, folder)
    for variable in native.variables:
        dump_array(
            native.variables[variable].solution, folder / f"solution_{variable}.csv"
        )
    capacities = []
    equations = []
    for technology in (*SIZES, "truck"):
        for slot in years:
            addition = (
                scalar(native.variables["capacity_addition"].solution, technology, slot)
                * HOURS
            )
            capacity = (
                scalar(native.variables["capacity"].solution, technology, slot) * HOURS
            )
            binary = scalar(installation.solution, technology, slot)
            capital = scalar(
                native.variables["cost_capex_overnight"].solution, technology, slot
            )
            annual = scalar(
                native.variables["cost_capex_yearly"].solution, technology, slot
            )
            capacities.append(
                {
                    "technology": technology,
                    "slot": slot,
                    "capacity_tonnes_per_year": capacity,
                    "addition_tonnes_per_year": addition,
                    "build_binary": binary if np.isfinite(binary) else None,
                    "upfront_EUR": capital,
                    "annual_capital_EUR": annual,
                }
            )
            near(
                name,
                "sharing",
                f"{technology} same capacity slot {slot}",
                capacity,
                scalar(native.variables["capacity"].solution, technology, 0) * HOURS,
            )
            if slot > 0:
                near(
                    name,
                    "sharing",
                    f"{technology} no later addition slot {slot}",
                    addition,
                    0,
                )
                near(
                    name,
                    "sharing",
                    f"{technology} no later investment slot {slot}",
                    scalar(
                        native.variables["capacity_investment"].solution,
                        technology,
                        slot,
                    ),
                    0,
                )
            if technology in SIZES:
                check(
                    name,
                    "MILP",
                    f"{technology} integer build slot {slot}",
                    binary,
                    "0 or 1",
                    min(abs(binary), abs(binary - 1)) < 1e-7,
                )
                near(
                    name,
                    "catalogue",
                    f"{technology} capacity equals selected size slot {slot}",
                    addition,
                    SIZES[technology] * binary,
                )
                near(
                    name,
                    "accounting",
                    f"{technology} fixed fee times binary slot {slot}",
                    capital,
                    BUILD_COST[technology] * binary,
                )
                near(
                    name,
                    "accounting",
                    f"{technology} annuity of initial purchase slot {slot}",
                    annual,
                    ANNUITY
                    * scalar(
                        native.variables["cost_capex_overnight"].solution, technology, 0
                    ),
                )
                key = {
                    "set_technologies": technology,
                    "set_capacity_types": "power",
                    "set_location": "source-sink",
                    "set_years": slot,
                }
                g_label = installation.labels.sel(key)
                upper = native.constraints[
                    "constraint_technology_max_capacity_addition"
                ]
                lower = native.constraints[
                    "constraint_technology_min_capacity_addition"
                ]
                capex = native.constraints["constraint_transport_technology_capex"]
                capital_equation = native.constraints["constraint_cost_capex_yearly"]
                initial_overnight_label = native.variables[
                    "cost_capex_overnight"
                ].labels.sel({**key, "set_years": 0})
                maximum_binary_coefficient = coefficient(upper, g_label, key)
                fee_coefficient = coefficient(
                    capex,
                    g_label,
                    {
                        "set_transport_technologies": technology,
                        "set_edges": "source-sink",
                        "set_years": slot,
                    },
                )
                annuity_coefficient = coefficient(
                    capital_equation, initial_overnight_label, key
                )
                near(
                    name,
                    "accounting",
                    f"{technology} generated fee coefficient slot {slot}",
                    fee_coefficient,
                    -BUILD_COST[technology],
                )
                near(
                    name,
                    "accounting",
                    f"{technology} generated annuity slot {slot}",
                    annuity_coefficient,
                    -ANNUITY,
                )
                if slot == 0:
                    near(
                        name,
                        "binary link",
                        f"{technology} upper bound linked to binary",
                        maximum_binary_coefficient,
                        -SIZES[technology] / HOURS,
                    )
                equations.append(
                    {
                        "technology": technology,
                        "slot": slot,
                        "max_bound_binary_coefficient": maximum_binary_coefficient,
                        "min_bound_binary_coefficient": coefficient(
                            lower, g_label, key
                        ),
                        "fixed_fee_binary_coefficient": fee_coefficient,
                        "initial_upfront_coefficient": annuity_coefficient,
                        "annual_fee_if_first_build_equals_one_EUR": fee_coefficient
                        * annuity_coefficient,
                    }
                )
    base.write_csv(folder / "capacities_and_binaries.csv", capacities)
    base.write_csv(folder / "binary_equation_trace.csv", equations)
    for row in annual_rows:
        times = step.time_steps.get_time_steps_year2operation(row["slot"])
        duration = p.time_steps_operation_duration.sel(set_time_steps_operation=times)
        for technology in (*SIZES, "truck"):
            row[technology + "_tonnes"] = float(
                (
                    native.variables["flow_transport"].solution.sel(
                        set_transport_technologies=technology,
                        set_edges="source-sink",
                        set_time_steps_operation=times,
                    )
                    * duration
                ).sum()
            )
        row["shed_tonnes"] = float(
            (
                native.variables["shed_demand"].solution.sel(
                    set_time_steps_operation=times
                )
                * duration
            ).sum()
        )
        row["captured_tonnes"] = float(
            (
                native.variables["flow_conversion_output"].solution.sel(
                    set_conversion_technologies="capture",
                    set_output_carriers="captured_carbon",
                    set_nodes="source",
                    set_time_steps_operation=times,
                )
                * duration
            ).sum()
        )
        near(name, "physical", f"slot {row['slot']} no shedding", row["shed_tonnes"], 0)
        near(
            name,
            "physical",
            f"slot {row['slot']} capture meets demand",
            row["captured_tonnes"],
            row["demand_tonnes"],
        )
        near(
            name,
            "physical",
            f"slot {row['slot']} delivered demand",
            sum(row[t + "_tonnes"] for t in (*SIZES, "truck")),
            row["demand_tonnes"],
        )
    base.write_csv(folder / "annual_operations.csv", annual_rows)
    running = (
        native.variables["cost_opex_yearly_total"].solution
        + native.variables["cost_carrier_total"].solution
        + native.variables["cost_carbon_emissions_total"].solution
    )
    weight = p.probability if fdm else 1
    capital_contribution = native.variables["cost_total"].solution - weight * running
    objective_trace = []
    for slot, probability in enumerate(specification["probability"]):
        key = {"set_years": slot}
        total_equation = native.constraints["constraint_cost_total"]
        annual_label = native.variables["cost_capex_yearly_total"].labels.sel(key)
        operation_label = native.variables["cost_opex_yearly_total"].labels.sel(key)
        capital_weight = -coefficient(total_equation, annual_label, key)
        operation_weight = -coefficient(total_equation, operation_label, key)
        near(
            name,
            "accounting",
            f"generated capital weight slot {slot}",
            capital_weight,
            1 if slot == 0 else 0,
        )
        near(
            name,
            "accounting",
            f"generated operation weight slot {slot}",
            operation_weight,
            probability,
        )
        objective_trace.append(
            {
                "slot": slot,
                "capital_weight": capital_weight,
                "operation_weight": operation_weight,
            }
        )
    base.write_csv(folder / "objective_equation_trace.csv", objective_trace)
    first_annual = float(
        native.variables["cost_capex_yearly_total"].solution.sel(set_years=0)
    )
    check(
        name,
        "accounting",
        "capital in first slot only",
        capital_contribution.values,
        [first_annual] + [0] * (len(years) - 1),
        np.allclose(capital_contribution, [first_annual] + [0] * (len(years) - 1)),
    )
    near(
        name,
        "accounting",
        "no discount between futures",
        float(
            abs(
                native.variables["net_present_cost"].solution
                - native.variables["cost_total"].solution
            ).max()
        ),
        0,
    )
    objective = float(native.objective.value)
    near(
        name,
        "hand benchmark",
        "objective",
        objective,
        specification["best"]["annual_total_EUR"],
    )
    for technology in SIZES:
        near(
            name,
            "hand benchmark",
            f"{technology} first build choice",
            scalar(installation.solution, technology),
            specification["best"][technology],
        )
    base.write_csv(
        folder / "capital_objective_contribution.csv",
        [
            {
                "slot": slot,
                "annual_capital_EUR": float(
                    native.variables["cost_capex_yearly_total"].solution.sel(
                        set_years=slot
                    )
                ),
                "capital_in_objective_EUR": float(
                    capital_contribution.sel(set_years=slot)
                ),
            }
            for slot in years
        ],
    )
    result = {
        "case": name,
        "solver": native.termination_condition,
        "binary_variable_count": binary_count,
        "hand_annual_cost_EUR": specification["best"]["annual_total_EUR"],
        "native_annual_cost_EUR": objective,
        "annual_capital_in_objective_EUR": float(capital_contribution.sum()),
        "expected_operating_cost_EUR": float((weight * running).sum()),
        "hand_choice": {t: specification["best"][t] for t in SIZES},
        "native_first_builds": {t: scalar(installation.solution, t) for t in SIZES},
        "catalogue_passed": all(
            r["passed"]
            for r in CHECKS
            if r["case"] == name and r["category"] == "catalogue"
        ),
        "hand_benchmark_passed": all(
            r["passed"]
            for r in CHECKS
            if r["case"] == name and r["category"] == "hand benchmark"
        ),
        "physical_passed": all(
            r["passed"]
            for r in CHECKS
            if r["case"] == name and r["category"] == "physical"
        ),
        "sharing_passed": all(
            r["passed"]
            for r in CHECKS
            if r["case"] == name and r["category"] == "sharing"
        ),
        "accounting_passed": all(
            r["passed"]
            for r in CHECKS
            if r["case"] == name and r["category"] == "accounting"
        ),
    }
    (folder / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUT)
    OUT = parser.parse_args().output.resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    before = source_hashes()
    diff_before = subprocess.check_output(["git", "diff", "--binary"], cwd=PROJECT)
    (OUT / "tested_worktree.patch").write_bytes(diff_before)
    (OUT / "source_sha256_before.json").write_text(json.dumps(before, indent=2) + "\n")
    for name, specification in CASES.items():
        build_inputs(name, specification)
    expected = hand_calculations()
    base.write_csv(
        ROOT / "hand_calculations/input_hashes.csv",
        [
            {
                "file": str(p.relative_to(ROOT)),
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in sorted((ROOT / "cases").rglob("*"))
            if p.is_file()
        ],
    )
    results = []
    for name, specification in expected.items():
        folder = OUT / name
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "run.log").open("w", buffering=1) as log:
            handler = logging.StreamHandler(log)
            logging.getLogger().addHandler(handler)
            try:
                with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                    result = run_case(name, specification)
            except Exception as error:
                traceback.print_exc(file=log)
                check(name, "runner", "completed", repr(error), "no exception", False)
                result = {"case": name, "error": repr(error)}
            finally:
                logging.getLogger().removeHandler(handler)
        results.append(result)
        print(json.dumps(result), flush=True)
    by_case = {result["case"]: result for result in results}
    original = by_case["stochastic_equal"]
    duplicated = by_case["stochastic_equal_duplicated"]
    if "error" not in original and "error" not in duplicated:
        near(
            "all",
            "duplication",
            "identical futures preserve native objective",
            duplicated["native_annual_cost_EUR"],
            original["native_annual_cost_EUR"],
        )
        near(
            "all",
            "duplication",
            "identical futures preserve hand objective",
            duplicated["hand_annual_cost_EUR"],
            original["hand_annual_cost_EUR"],
        )
        near(
            "all",
            "duplication",
            "identical futures preserve annual capital charge",
            duplicated["annual_capital_in_objective_EUR"],
            original["annual_capital_in_objective_EUR"],
        )
        for technology in SIZES:
            near(
                "all",
                "duplication",
                f"identical futures preserve {technology} build choice",
                duplicated["native_first_builds"][technology],
                original["native_first_builds"][technology],
            )
    after = source_hashes()
    source_unchanged = before == after
    diff_unchanged = diff_before == subprocess.check_output(
        ["git", "diff", "--binary"], cwd=PROJECT
    )
    (OUT / "source_sha256_after.json").write_text(json.dumps(after, indent=2) + "\n")
    check(
        "all",
        "scope",
        "production source unchanged",
        source_unchanged,
        True,
        source_unchanged,
    )
    check(
        "all", "scope", "tracked diff unchanged", diff_unchanged, True, diff_unchanged
    )
    pd.DataFrame(CHECKS).to_csv(OUT / "checks.csv", index=False)
    pd.DataFrame(
        [
            {
                k: v
                for k, v in r.items()
                if k not in ("hand_choice", "native_first_builds")
            }
            for r in results
        ]
    ).to_csv(OUT / "comparison.csv", index=False)
    summary = {
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT, text=True
        ).strip(),
        "cases": results,
        "checks_passed": sum(r["passed"] for r in CHECKS),
        "checks_failed": sum(not r["passed"] for r in CHECKS),
        "failed_checks": [r for r in CHECKS if not r["passed"]],
        "production_source_unchanged": source_unchanged,
        "tracked_diff_unchanged": diff_unchanged,
        "runner_changed_formulation": False,
        "tested_uncommitted_changes": bool(diff_before),
        "deterministic_controls": EXPECTED_FUTURE_CONTROLS,
        "duplication_has_positive_capital": (
            original.get("annual_capital_in_objective_EUR", 0) > 1e-7
            and duplicated.get("annual_capital_in_objective_EUR", 0) > 1e-7
        ),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Full results: {OUT}")
    return 0 if all(r["passed"] for r in CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
