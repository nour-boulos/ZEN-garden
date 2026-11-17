"""Run unmodified native CCS models and save solver evidence and hand comparisons.

No constraint, bound, objective, or variable is added or changed by this runner.
An exit status of 1 means at least one intended catalogue acceptance check failed.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import logging
import math
import platform
import subprocess
import sys
import traceback
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

from zen_garden.config import Config
from zen_garden.model.schema import ModelSchema
from zen_garden.workflow.optimization_step import OptimizationStep
from zen_garden.workflow.optimization_workflow import OptimizationWorkflow

from .build_dataset import CASES, HAND_ROOT, HOURS, ROOT, SIZES

PROJECT = ROOT.parent.parent
OUT = PROJECT / "checkpoints/stochastic_fixed_investment/fdm_ccs_current"
CHECKS = []


def record(case, category, name, passed, actual, expected):
    CHECKS.append(
        {
            "case": case,
            "category": category,
            "check": name,
            "passed": bool(passed),
            "actual": str(actual),
            "expected": str(expected),
        }
    )


def near(case, category, name, actual, expected):
    record(
        case,
        category,
        name,
        math.isclose(float(actual), float(expected), rel_tol=1e-7, abs_tol=1e-7),
        actual,
        expected,
    )


def source_hashes():
    return {
        str(p.relative_to(PROJECT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((PROJECT / "zen_garden").rglob("*.py"))
    }


def dump_array(array, path, name="value"):
    if array.ndim:
        array.to_series().dropna().rename(name).reset_index().to_csv(path, index=False)
    else:
        pd.DataFrame([{name: float(array)}]).to_csv(path, index=False)


def scalar(solution, tech, slot=0, location="source-sink"):
    return float(
        solution.sel(
            set_technologies=tech,
            set_capacity_types="power",
            set_location=location,
            set_years=slot,
        )
    )


def equation_terms(model, folder):
    rows = []
    rendered = []
    for name in (
        "constraint_technology_max_capacity_addition",
        "constraint_technology_min_capacity_addition",
        "constraint_transport_technology_capex",
        "constraint_technology_lifetime",
        "constraint_cost_capex_yearly",
        "constraint_cost_total",
        "constraint_net_present_cost",
        "constraint_limit_shed_demand",
    ):
        if name not in model.lp_model.constraints:
            continue
        constraint = model.lp_model.constraints[name]
        rendered.extend([f"\n{name}\n", str(constraint), "\n"])
        data = (
            constraint.coeffs.to_series()
            .rename("coefficient")
            .to_frame()
            .join(constraint.vars.to_series().rename("variable_label"))
        )
        data = data[(data.variable_label >= 0) & (data.coefficient != 0)].reset_index()
        data.insert(0, "constraint", name)
        data["variable"] = [
            model.lp_model.variables.get_label_position(int(label))
            for label in data.variable_label
        ]
        rows.extend(data.to_dict("records"))
    pd.DataFrame(rows).to_csv(folder / "constraint_terms.csv", index=False)
    (folder / "constraint_equations.txt").write_text("".join(rendered))


def run_case(name, specification):
    folder = OUT / name
    folder.mkdir(parents=True, exist_ok=True)
    dataset = ROOT / "cases" / name
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
    p = model.parameters
    slots = len(specification["probabilities"])
    binary = specification["kind"] != "continuous"
    near(name, "input", "number of fictitious operating slots", len(years), slots)
    record(
        name,
        "input",
        "FDM mode",
        config.system.use_stochastic_fdm == (slots > 1),
        config.system.use_stochastic_fdm,
        slots > 1,
    )
    record(
        name,
        "input",
        "scenario tree disabled",
        workflow.model_schema.scenario_tree is None,
        workflow.model_schema.scenario_tree,
        None,
    )
    record(
        name,
        "input",
        "all shedding prices infinite",
        np.isposinf(p.price_shed_demand).all().item(),
        p.price_shed_demand.values,
        "all +inf",
    )
    near(name, "input", "capture conversion ratio", float(p.conversion_factor.min()), 1)
    near(
        name,
        "input",
        "capture capital cost",
        float(abs(p.capex_specific_conversion).max()),
        0,
    )
    near(
        name,
        "input",
        "capture operating cost",
        float(abs(p.opex_specific_variable.sel(set_technologies="capture")).max()),
        0,
    )
    near(name, "input", "discount rate", float(p.discount_rate), 0)
    for technology in ("capture", "truck", *(SIZES if binary else ["pipeline"])):
        near(
            name,
            "input",
            f"{technology} lifetime",
            float(p.lifetime.sel(set_technologies=technology)),
            slots,
        )
        near(
            name,
            "input",
            f"{technology} depreciation",
            float(p.depreciation_time.sel(set_technologies=technology)),
            slots,
        )
        if slots > 1:
            near(
                name,
                "input",
                f"{technology} later addition maximum",
                float(
                    p.capacity_addition_max.sel(
                        set_technologies=technology,
                        set_capacity_types="power",
                        set_years=1,
                    )
                ),
                0,
            )
    if slots > 1:
        near(name, "input", "probabilities sum to one", float(p.probability.sum()), 1)
        near(name, "input", "unmet demand threshold", float(p.expected_loss_of_load), 0)
        for slot, probability in enumerate(specification["probabilities"]):
            near(
                name,
                "input",
                f"slot {slot} probability",
                float(p.probability.sel(set_years=slot)),
                probability,
            )
    for technology, size in SIZES.items() if binary else []:
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
        cost_key = {
            "set_transport_technologies": technology,
            "set_edges": "source-sink",
            "set_years": 0,
        }
        near(
            name,
            "input",
            f"{technology} per-capacity cost",
            float(p.capex_specific_transport.sel(cost_key)) / HOURS,
            4 if specification["kind"] == "capacity_cost" else 0,
        )
        near(
            name,
            "input",
            f"{technology} fixed investment cost",
            float(p.transport_capex_distance.sel(cost_key)),
            4 * size if specification["kind"] == "fixed_cost" else 0,
        )
    loaded_names = [
        "demand",
        "price_shed_demand",
        "capacity_addition_max",
        "capacity_addition_min",
        "capacity_limit",
        "capex_specific_transport",
        "capex_per_distance_transport",
        "transport_capex_distance",
        "lifetime",
        "depreciation_time",
        "conversion_factor",
        "opex_specific_variable",
        "time_steps_operation_duration",
    ]
    if slots > 1:
        loaded_names += ["probability", "expected_loss_of_load"]
    for parameter in loaded_names:
        dump_array(getattr(p, parameter), folder / f"loaded_{parameter}.csv")
    if not all(
        r["passed"] for r in CHECKS if r["case"] == name and r["category"] == "input"
    ):
        raise AssertionError(
            "Input checks failed; do not interpret a solve against the hand calculation"
        )

    step.solve("")  # Existing v3 solve lifecycle, including sanitize_zeros=True.
    record(
        name,
        "solve",
        "solver termination",
        step.optimality and model.lp_model.termination_condition == "optimal",
        model.lp_model.termination_condition,
        "optimal",
    )
    if not step.optimality:
        return {"case": name, "status": "not optimal"}
    model.lp_model.to_file(folder / "solved_model.lp")
    model.lp_model.solution.to_netcdf(folder / "solution.nc")
    for variable in model.lp_model.variables:
        dump_array(
            model.variables[variable].solution, folder / f"solution_{variable}.csv"
        )
    equation_terms(model, folder)
    for constraint_name in model.lp_model.constraints:
        c = model.lp_model.constraints[constraint_name]
        record(
            name,
            "solve",
            f"finite active terms: {constraint_name}",
            not ((c.vars >= 0) & ~np.isfinite(c.coeffs)).any().item(),
            "checked after native solve",
            "all finite",
        )

    solution = {
        v: model.variables[v].solution
        for v in (
            "capacity",
            "capacity_addition",
            "capacity_investment",
            "cost_capex_overnight",
            "cost_capex_yearly",
            "technology_installation",
            "flow_transport",
            "flow_conversion_output",
            "shed_demand",
        )
        if v in model.lp_model.variables
    }
    capacity_rows = []
    pipelines = list(SIZES) if binary else ["pipeline"]
    for technology in pipelines + ["truck"]:
        for slot in range(slots):
            g = (
                scalar(solution["technology_installation"], technology, slot)
                if "technology_installation" in solution
                else float("nan")
            )
            addition = scalar(solution["capacity_addition"], technology, slot) * HOURS
            capacity = scalar(solution["capacity"], technology, slot) * HOURS
            capacity_rows.append(
                {
                    "technology": technology,
                    "slot": slot,
                    "capacity_tonnes_per_year": capacity,
                    "addition_tonnes_per_year": addition,
                    "investment_tonnes_per_year": scalar(
                        solution["capacity_investment"], technology, slot
                    )
                    * HOURS,
                    "installation_binary": g if np.isfinite(g) else None,
                    "overnight_EUR": scalar(
                        solution["cost_capex_overnight"], technology, slot
                    ),
                    "annual_capital_EUR": scalar(
                        solution["cost_capex_yearly"], technology, slot
                    ),
                }
            )
            near(
                name,
                "sharing",
                f"{technology} same capacity in slot {slot}",
                capacity,
                scalar(solution["capacity"], technology, 0) * HOURS,
            )
            if slot > 0:
                near(name, "sharing", f"{technology} no later addition", addition, 0)
                near(
                    name,
                    "sharing",
                    f"{technology} no later investment",
                    scalar(solution["capacity_investment"], technology, slot),
                    0,
                )
            if technology in SIZES:
                record(
                    name,
                    "catalogue",
                    f"{technology} binary integer in slot {slot}",
                    min(abs(g), abs(g - 1)) < 1e-7,
                    g,
                    "0 or 1",
                )
                near(
                    name,
                    "catalogue",
                    f"{technology} size linked to binary in slot {slot}",
                    addition,
                    SIZES[technology] * g,
                )
    pd.DataFrame(capacity_rows).to_csv(
        folder / "capacity_and_binaries.csv", index=False
    )

    annual_rows = []
    for slot, demand in enumerate(specification["demands"]):
        operations = step.time_steps.get_time_steps_year2operation(slot)
        duration = p.time_steps_operation_duration.sel(
            set_time_steps_operation=operations
        )
        actual_demand = float(
            (
                p.demand.sel(
                    set_carriers="captured_carbon",
                    set_nodes="sink",
                    set_time_steps_operation=operations,
                )
                * duration
            ).sum()
        )
        near(
            name, "input", f"slot {slot} annual duration", float(duration.sum()), HOURS
        )
        near(name, "input", f"slot {slot} annual demand", actual_demand, demand)
        annual_flows = {
            tech: float(
                (
                    solution["flow_transport"].sel(
                        set_transport_technologies=tech,
                        set_edges="source-sink",
                        set_time_steps_operation=operations,
                    )
                    * duration
                ).sum()
            )
            for tech in pipelines + ["truck"]
        }
        capture = float(
            (
                solution["flow_conversion_output"].sel(
                    set_conversion_technologies="capture",
                    set_output_carriers="captured_carbon",
                    set_nodes="source",
                    set_time_steps_operation=operations,
                )
                * duration
            ).sum()
        )
        shed = float(
            (
                solution["shed_demand"].sel(set_time_steps_operation=operations)
                * duration
            ).sum()
        )
        near(name, "physical", f"slot {slot} no shedding", shed, 0)
        near(name, "physical", f"slot {slot} capture equals demand", capture, demand)
        near(
            name,
            "physical",
            f"slot {slot} transport equals demand",
            sum(annual_flows.values()),
            demand,
        )
        near(
            name,
            "benchmark",
            f"slot {slot} pipeline flow",
            sum(annual_flows[t] for t in pipelines),
            specification["pipeline_flow_tonnes"][slot],
        )
        near(
            name,
            "benchmark",
            f"slot {slot} truck flow",
            annual_flows["truck"],
            specification["truck_flow_tonnes"][slot],
        )
        annual_rows.append(
            {
                "slot": slot,
                "fictitious_year": 2026 + slot,
                "probability": specification["probabilities"][slot],
                "demand_tonnes": actual_demand,
                "capture_tonnes": capture,
                "shed_tonnes": shed,
                **{f"{t}_tonnes": flow for t, flow in annual_flows.items()},
            }
        )
    pd.DataFrame(annual_rows).to_csv(folder / "annual_operations.csv", index=False)
    objective = float(model.lp_model.objective.value)
    near(
        name,
        "benchmark",
        "objective equals independent hand optimum",
        objective,
        specification["hand_optimum"]["total_EUR"],
    )
    first_capital = float(solution["cost_capex_overnight"].sel(set_years=0).sum())
    annual_capital = model.variables["cost_capex_yearly_total"].solution
    first_annual_capital = float(annual_capital.sel(set_years=0))
    running = (
        model.variables["cost_opex_yearly_total"].solution
        + model.variables["cost_carrier_total"].solution
        + model.variables["cost_carbon_emissions_total"].solution
    )
    probability = p.probability if config.system.use_stochastic_fdm else 1
    capital_contribution = (
        model.variables["cost_total"].solution - probability * running
    )
    capital_charged = float(capital_contribution.sum())
    dump_array(capital_contribution, folder / "capital_objective_contribution.csv")
    expected_operation = sum(
        row["probability"]
        * (sum(row[f"{t}_tonnes"] for t in pipelines) + 8 * row["truck_tonnes"])
        for row in annual_rows
    )
    near(
        name,
        "accounting",
        "one annual capital charge in objective",
        capital_charged,
        first_annual_capital,
    )
    near(
        name,
        "accounting",
        "annual capital variables retained in all futures",
        float(annual_capital.sum()),
        slots * first_annual_capital,
    )
    near(
        name,
        "accounting",
        "objective matches annual capital and expected operations",
        objective,
        first_annual_capital + expected_operation,
    )
    result = {
        "case": name,
        "solver": model.lp_model.termination_condition,
        "actual_objective_EUR": objective,
        "hand_objective_EUR": specification["hand_optimum"]["total_EUR"],
        "actual_upfront_capital_EUR": first_capital,
        "actual_annual_capital_EUR": first_annual_capital,
        "actual_capital_in_objective_EUR": capital_charged,
        "actual_expected_operation_EUR": expected_operation,
        "catalogue_passed": all(
            r["passed"]
            for r in CHECKS
            if r["case"] == name and r["category"] == "catalogue"
        ),
        "benchmark_passed": all(
            r["passed"]
            for r in CHECKS
            if r["case"] == name and r["category"] == "benchmark"
        ),
        "input_passed": all(
            r["passed"]
            for r in CHECKS
            if r["case"] == name and r["category"] == "input"
        ),
        "capacity_and_binaries": capacity_rows,
        "annual_operations": annual_rows,
    }
    (folder / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="+", choices=list(CASES))
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    OUT = args.output.resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    before = source_hashes()
    (OUT / "source_sha256_before.json").write_text(json.dumps(before, indent=2) + "\n")
    (OUT / "git_status_before.txt").write_text(
        subprocess.check_output(
            ["git", "status", "--short", "--branch"], cwd=PROJECT, text=True
        )
    )
    (OUT / "source_diff_before.patch").write_bytes(
        subprocess.check_output(["git", "diff", "--binary"], cwd=PROJECT)
    )
    (OUT / "versions.json").write_text(
        json.dumps(
            {
                "python": platform.python_version(),
                **{
                    package: version(package)
                    for package in (
                        "linopy",
                        "highspy",
                        "xarray",
                        "pandas",
                        "zen-garden",
                    )
                },
            },
            indent=2,
        )
        + "\n"
    )
    expectations = json.loads((HAND_ROOT / "expected_results.json").read_text())
    rows = []
    selected_cases = args.cases if args.cases is not None else list(expectations)
    for name in selected_cases:
        specification = expectations[name]
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
                record(
                    name, "runner", "case completed", False, repr(error), "no exception"
                )
                result = {"case": name, "status": "runner failed", "error": repr(error)}
            finally:
                logging.getLogger().removeHandler(handler)
        rows.append(result)
        print(
            json.dumps(
                {
                    key: value
                    for key, value in result.items()
                    if key not in ("capacity_and_binaries", "annual_operations")
                }
            ),
            flush=True,
        )
    after = source_hashes()
    (OUT / "source_sha256_after.json").write_text(json.dumps(after, indent=2) + "\n")
    source_unchanged = before == after
    diff_unchanged = (
        OUT / "source_diff_before.patch"
    ).read_bytes() == subprocess.check_output(["git", "diff", "--binary"], cwd=PROJECT)
    record(
        "all",
        "scope",
        "production Python source unchanged",
        source_unchanged,
        source_unchanged,
        True,
    )
    record(
        "all", "scope", "tracked diff unchanged", diff_unchanged, diff_unchanged, True
    )
    pd.DataFrame(CHECKS).to_csv(OUT / "checks.csv", index=False)
    columns = [
        "case",
        "solver",
        "actual_objective_EUR",
        "hand_objective_EUR",
        "actual_upfront_capital_EUR",
        "actual_annual_capital_EUR",
        "actual_capital_in_objective_EUR",
        "actual_expected_operation_EUR",
        "catalogue_passed",
        "benchmark_passed",
        "input_passed",
        "error",
    ]
    pd.DataFrame(rows).reindex(columns=columns).to_csv(
        OUT / "comparison.csv", index=False
    )
    summary = {
        "cases": rows,
        "source_unchanged": source_unchanged,
        "tracked_diff_unchanged": diff_unchanged,
        "checks_passed": sum(r["passed"] for r in CHECKS),
        "checks_failed": sum(not r["passed"] for r in CHECKS),
        "failed_checks": [r for r in CHECKS if not r["passed"]],
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Evidence: {OUT}", flush=True)
    return 0 if all(r["passed"] for r in CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
