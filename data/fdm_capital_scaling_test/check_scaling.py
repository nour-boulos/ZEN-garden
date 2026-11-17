"""Small input-only experiments on FDM capital normalization; no formulation edits."""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import shutil
import subprocess
from pathlib import Path

import numpy as np
import yaml

from data.fdm_ccs_binary_test.build_dataset import write_csv, write_yaml
from data.fdm_ccs_binary_test.run_checks import dump_array, equation_terms
from zen_garden.config import Config
from zen_garden.model.schema import ModelSchema
from zen_garden.workflow.optimization_step import OptimizationStep
from zen_garden.workflow.optimization_workflow import OptimizationWorkflow

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent.parent
OUT = PROJECT / "checkpoints/stochastic_fixed_investment/11_capital_scaling_test"
BASE = PROJECT / "data/fdm_ccs_binary_test/cases/continuous_equal"
HOURS = 8760
RATE = 0.05
LIFETIME = 50
QUOTE = 20.0
ANNUITY = RATE / (1 - (1 + RATE) ** -LIFETIME)
PROBABILITIES = [9 / 30, 7 / 30, 1 / 30, 9 / 30, 4 / 30]
DEMANDS = [40, 100, 40, 100, 40]


def source_hashes():
    return {
        str(p.relative_to(PROJECT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((PROJECT / "zen_garden").rglob("*.py"))
    }


def build_case(name, copies, normalize):
    dataset = ROOT / "cases" / name
    probabilities = [p / copies for _ in range(copies) for p in PROBABILITIES]
    demands = DEMANDS * copies
    count = len(demands)
    quote_input = QUOTE / count if normalize else QUOTE
    if not dataset.exists():
        shutil.copytree(BASE, dataset)
        system = yaml.safe_load((dataset / "system.yaml").read_text())
        system["optimized_years"] = count
        write_yaml(dataset / "system.yaml", system)
        energy = yaml.safe_load((dataset / "energy_system/attributes.yaml").read_text())
        energy["discount_rate"]["default_value"] = RATE
        write_yaml(dataset / "energy_system/attributes.yaml", energy)
        write_csv(
            dataset / "energy_system/probability.csv",
            [{"year": 2026 + s, "probability": p} for s, p in enumerate(probabilities)],
        )
        write_csv(
            dataset / "set_carriers/captured_carbon/demand_yearly_variation.csv",
            [
                {"node": node, "year": 2026 + s, "demand_yearly_variation": demand / 40}
                for node in ("source", "sink")
                for s, demand in enumerate(demands)
            ],
        )
        for path in dataset.glob("set_technologies/*/*/attributes.yaml"):
            attributes = yaml.safe_load(path.read_text())
            attributes["lifetime"]["default_value"] = LIFETIME
            attributes["depreciation_time"]["default_value"] = LIFETIME
            if path.parent.name == "pipeline":
                attributes["capex_specific_transport"]["default_value"] = (
                    quote_input * HOURS
                )
            write_yaml(path, attributes)
            write_csv(
                path.parent / "capacity_addition_max.csv",
                [
                    {
                        "year": 2026 + s,
                        "capacity_addition_max": float("inf") if s == 0 else 0,
                    }
                    for s in range(count)
                ],
            )
    candidates = []
    for capacity in range(101):
        operation = sum(
            p * (min(d, capacity) + 8 * max(d - capacity, 0))
            for p, d in zip(probabilities, demands, strict=True)
        )
        capital = count * ANNUITY * quote_input * capacity
        candidates.append(
            {
                "case": name,
                "capacity_tonnes_per_year": capacity,
                "capital_EUR": capital,
                "expected_operation_EUR": operation,
                "total_EUR": capital + operation,
                "one_annual_capital_reference_EUR": ANNUITY * QUOTE * capacity
                + operation,
            }
        )
    hand = min(candidates, key=lambda r: r["total_EUR"])
    write_csv(ROOT / "hand_calculations" / f"{name}.csv", candidates)
    specification = {
        "name": name,
        "slots": count,
        "probabilities": probabilities,
        "demands": demands,
        "normalized_inputs": normalize,
        "quote_before_test_scaling": QUOTE,
        "quote_loaded": quote_input,
        "hand_optimum": hand,
    }
    return dataset, specification


def run_case(dataset, specification):
    name = specification["name"]
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
    parameters = model.parameters
    assert config.system.use_stochastic_fdm
    assert workflow.model_schema.scenario_tree is None
    assert np.isclose(parameters.discount_rate, RATE)
    assert np.allclose(parameters.lifetime, LIFETIME)
    assert np.allclose(parameters.depreciation_time, LIFETIME)
    assert np.allclose(parameters.probability, specification["probabilities"])
    assert np.isclose(float(parameters.probability.sum()), 1)
    assert np.isposinf(parameters.price_shed_demand).all()
    assert float(parameters.expected_loss_of_load) == 0
    assert np.allclose(
        parameters.capex_specific_transport.sel(set_transport_technologies="pipeline")
        / HOURS,
        specification["quote_loaded"],
    )
    assert "technology_installation" not in model.lp_model.variables
    for name_parameter in (
        "probability",
        "discount_rate",
        "lifetime",
        "depreciation_time",
        "capacity_addition_max",
        "capex_specific_transport",
        "demand",
        "time_steps_operation_duration",
    ):
        dump_array(
            getattr(parameters, name_parameter), folder / f"loaded_{name_parameter}.csv"
        )
    step.solve("")
    assert step.optimality and model.lp_model.termination_condition == "optimal"
    model.lp_model.to_file(folder / "solved_model.lp")
    model.lp_model.solution.to_netcdf(folder / "solution.nc")
    for variable in model.lp_model.variables:
        dump_array(
            model.variables[variable].solution, folder / f"solution_{variable}.csv"
        )
    equation_terms(model, folder)
    capacity = (
        model.variables["capacity"].solution.sel(
            set_technologies="pipeline",
            set_capacity_types="power",
            set_location="source-sink",
        )
        * HOURS
    )
    chosen = float(capacity.sel(set_years=0))
    assert np.allclose(capacity, chosen)
    assert np.isclose(chosen, specification["hand_optimum"]["capacity_tonnes_per_year"])
    for variable in ("capacity_addition", "capacity_investment"):
        assert (
            float(
                abs(model.variables[variable].solution.sel(set_years=years[1:])).max()
            )
            < 1e-8
        )
    assert float(abs(model.variables["shed_demand"].solution).max()) < 1e-8
    objective = float(model.lp_model.objective.value)
    capital = float(model.variables["cost_capex_yearly_total"].solution.sum())
    expected_capital = (
        specification["slots"] * ANNUITY * specification["quote_loaded"] * chosen
    )
    assert np.isclose(capital, expected_capital)
    assert np.isclose(objective, specification["hand_optimum"]["total_EUR"])
    annual_rows = []
    for slot, (demand, probability) in enumerate(
        zip(specification["demands"], specification["probabilities"], strict=True)
    ):
        times = step.time_steps.get_time_steps_year2operation(slot)
        duration = parameters.time_steps_operation_duration.sel(
            set_time_steps_operation=times
        )
        assert np.isclose(float(duration.sum()), HOURS)
        actual_demand = float(
            (
                parameters.demand.sel(
                    set_carriers="captured_carbon",
                    set_nodes="sink",
                    set_time_steps_operation=times,
                )
                * duration
            ).sum()
        )
        assert np.isclose(actual_demand, demand)
        flows = {
            tech: float(
                (
                    model.variables["flow_transport"].solution.sel(
                        set_transport_technologies=tech,
                        set_edges="source-sink",
                        set_time_steps_operation=times,
                    )
                    * duration
                ).sum()
            )
            for tech in ("pipeline", "truck")
        }
        assert np.isclose(flows["pipeline"] + flows["truck"], demand)
        annual_rows.append(
            {
                "slot": slot,
                "probability": probability,
                "demand_tonnes": actual_demand,
                "pipeline_tonnes": flows["pipeline"],
                "truck_tonnes": flows["truck"],
            }
        )
    write_csv(folder / "annual_operations.csv", annual_rows)
    result = {
        "case": name,
        "slots": specification["slots"],
        "normalized_inputs": specification["normalized_inputs"],
        "pipeline_capacity_tonnes_per_year": chosen,
        "capital_EUR": capital,
        "expected_operation_EUR": objective - capital,
        "objective_EUR": objective,
        "hand_objective_EUR": specification["hand_optimum"]["total_EUR"],
        "expected_demand_tonnes": sum(
            p * d
            for p, d in zip(
                specification["probabilities"], specification["demands"], strict=True
            )
        ),
        "solver": model.lp_model.termination_condition,
        "zero_shedding": True,
        "shared_capacity": True,
        "no_later_investment": True,
    }
    (folder / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    before = source_hashes()
    diff_before = subprocess.check_output(["git", "diff", "--binary"], cwd=PROJECT)
    (OUT / "source_sha256_before.json").write_text(json.dumps(before, indent=2) + "\n")
    specifications = []
    results = []
    for count, copies, normalize in (
        (5, 1, False),
        (10, 2, False),
        (5, 1, True),
        (10, 2, True),
    ):
        name = f"slots_{count}_{'scaled_capex' if normalize else 'unchanged_capex'}"
        dataset, specification = build_case(name, copies, normalize)
        specifications.append(specification)
        folder = OUT / name
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "run.log").open("w", buffering=1) as log:
            handler = logging.StreamHandler(log)
            logging.getLogger().addHandler(handler)
            try:
                with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                    result = run_case(dataset, specification)
            finally:
                logging.getLogger().removeHandler(handler)
        results.append(result)
        print(json.dumps(result), flush=True)
    # Duplicating each future and halving its probability preserves its distribution.
    assert all(np.isclose(r["expected_demand_tonnes"], 72) for r in results)
    assert np.isclose(results[2]["objective_EUR"], results[3]["objective_EUR"])
    assert np.isclose(
        results[2]["pipeline_capacity_tonnes_per_year"],
        results[3]["pipeline_capacity_tonnes_per_year"],
    )
    after = source_hashes()
    assert before == after
    assert diff_before == subprocess.check_output(
        ["git", "diff", "--binary"], cwd=PROJECT
    )
    (OUT / "source_sha256_after.json").write_text(json.dumps(after, indent=2) + "\n")
    (ROOT / "hand_calculations/specifications.json").write_text(
        json.dumps(specifications, indent=2) + "\n"
    )
    write_csv(OUT / "comparison.csv", results)
    write_csv(
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
    summary = {
        "annuity": ANNUITY,
        "rate": RATE,
        "lifetime": LIFETIME,
        "cases": results,
        "production_source_unchanged": before == after,
        "tracked_diff_unchanged": True,
        "uploaded_dataset_read_or_solved_by_test": False,
        "normalization_only_in_separate_test_inputs": True,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"All four small-model checks passed. Evidence: {OUT}")


if __name__ == "__main__":
    main()
