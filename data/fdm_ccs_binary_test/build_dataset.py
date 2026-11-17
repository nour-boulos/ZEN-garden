"""Build CCS input cases and independent catalogue enumeration; change no model code."""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
HAND_ROOT = ROOT / "hand_calculations_annual_capex_once"
HOURS = 8760
YEAR = 2026
SIZES = {"pipeline_small": 60.0, "pipeline_large": 100.0}
CASES = {
    "continuous_equal": {"kind": "continuous", "probabilities": [0.5, 0.5]},
    "binary_capacity_cost_equal": {
        "kind": "capacity_cost",
        "probabilities": [0.5, 0.5],
    },
    "binary_fixed_cost_equal": {
        "kind": "fixed_cost",
        "probabilities": [0.5, 0.5],
    },
    "binary_fixed_cost_high_probability": {
        "kind": "fixed_cost",
        "probabilities": [0.2, 0.8],
    },
    "deterministic_binary_control": {
        "kind": "fixed_cost",
        "probabilities": [1.0],
    },
}


def attribute(value, unit=None):
    result = {"default_value": value}
    if unit is not None:
        result["unit"] = unit
    return result


def write_yaml(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def technology_attributes(slots, capacity=100.0):
    return {
        "capacity_addition_min": attribute(0.0, "tonne/hour"),
        "capacity_addition_max": attribute(float("inf"), "tonne/hour"),
        "capacity_limit": attribute(capacity / HOURS, "tonne/hour"),
        "capacity_lower_limit": attribute(0.0, "tonne/hour"),
        "capacity_existing": attribute(0.0, "tonne/hour"),
        "capacity_investment_existing": attribute(0.0, "tonne/hour"),
        "capacity_addition_unbounded": attribute(0.0, "tonne/hour"),
        "min_load": attribute(0.0, "1"),
        "max_load": attribute(1.0, "1"),
        "lifetime": attribute(float(slots), "1"),
        "depreciation_time": attribute(float(slots), "1"),
        "construction_time": attribute(0.0, "1"),
        "max_diffusion_rate": attribute(float("inf"), "1"),
        "opex_specific_variable": attribute(0.0, "Euro/tonne"),
        "opex_specific_fixed": attribute(0.0, "Euro/(tonne/hour)"),
    }


def addition_file(folder, maximum, slots):
    write_csv(
        folder / "capacity_addition_max.csv",
        [
            {"year": YEAR + slot, "capacity_addition_max": maximum if slot == 0 else 0}
            for slot in range(slots)
        ],
    )


def build_case(name, specification):
    folder = ROOT / "cases" / name
    if folder.exists():
        raise FileExistsError(f"Refusing to overwrite existing inputs: {folder}")
    probabilities = specification["probabilities"]
    slots = len(probabilities)
    binary = specification["kind"] != "continuous"
    pipelines = list(SIZES) if binary else ["pipeline"]
    write_yaml(
        folder / "system.yaml",
        {
            "set_conversion_technologies": ["capture"],
            "set_transport_technologies": pipelines + ["truck"],
            "set_storage_technologies": [],
            "set_nodes": ["source", "sink"],
            "reference_year": YEAR,
            "optimized_years": slots,
            "interval_between_years": 1,
            "total_hours_per_year": HOURS,
            "unaggregated_time_steps_per_year": HOURS,
            "aggregated_time_steps_per_year": 1,
            "conduct_time_series_aggregation": True,
            "use_rolling_horizon": False,
            "conduct_scenario_analysis": False,
            "use_scenariotree": False,
            "use_stochastic_fdm": slots > 1,
            "allow_investment": True,
            "double_capex_transport": True,
        },
    )
    write_yaml(
        folder / "config.yaml",
        {
            "solver": {
                "name": "highs",
                "check_unit_consistency": True,
                "save_duals": False,
                "round_parameters": False,
                "rounding_decimal_points_units": 12,
                "use_scaling": False,
            }
        },
    )
    energy = folder / "energy_system"
    write_yaml(
        energy / "base_units.yaml", {"unit": ["hour", "GW", "km", "tonne", "Euro"]}
    )
    (energy / "unit_definitions.txt").write_text("# Use standard Pint units.\n")
    write_csv(
        energy / "set_nodes.csv",
        [
            {"node": "source", "lon": 0.0, "lat": 0.0},
            {"node": "sink", "lon": 0.01, "lat": 0.0},
        ],
    )
    write_csv(
        energy / "set_edges.csv",
        [{"edge": "source-sink", "node_from": "source", "node_to": "sink"}],
    )
    write_yaml(
        energy / "attributes.yaml",
        {
            "discount_rate": attribute(0.0, "1"),
            "carbon_emissions_annual_limit": attribute(float("inf"), "tonne"),
            "carbon_emissions_budget": attribute(float("inf"), "tonne"),
            "carbon_emissions_cumulative_existing": attribute(0.0, "tonne"),
            "price_carbon_emissions": attribute(0.0, "Euro/tonne"),
            "price_carbon_emissions_budget_overshoot": attribute(1.0, "Euro/tonne"),
            "price_carbon_emissions_annual_overshoot": attribute(1.0, "Euro/tonne"),
            "knowledge_depreciation_rate": attribute(0.0, "1"),
            "knowledge_spillover_rate": attribute(float("inf"), "1"),
            "market_share_unbounded": attribute(0.0, "1"),
            **(
                {
                    "probability": attribute(probabilities[0], "1"),
                    "expected_loss_of_load": attribute(0.0, "1"),
                }
                if slots > 1
                else {}
            ),
        },
    )
    if slots > 1:
        write_csv(
            energy / "probability.csv",
            [{"year": YEAR + s, "probability": p} for s, p in enumerate(probabilities)],
        )
    for carrier in ("raw_emissions", "captured_carbon"):
        carrier_folder = folder / "set_carriers" / carrier
        write_yaml(
            carrier_folder / "attributes.yaml",
            {
                "carbon_intensity_carrier_import": attribute(0.0, "tonne/tonne"),
                "carbon_intensity_carrier_export": attribute(0.0, "tonne/tonne"),
                "demand": attribute(0.0, "tonne/hour"),
                "price_shed_demand": attribute(float("inf"), "Euro/tonne"),
                "availability_import": attribute(0.0, "tonne/hour"),
                "availability_export": attribute(0.0, "tonne/hour"),
                "availability_import_yearly": attribute(float("inf"), "tonne"),
                "availability_export_yearly": attribute(0.0, "tonne"),
                "price_import": attribute(0.0, "Euro/tonne"),
                "price_export": attribute(0.0, "Euro/tonne"),
            },
        )
        write_csv(
            carrier_folder / "demand.csv",
            [
                {
                    "node": node,
                    "demand": (
                        40 / HOURS
                        if carrier == "captured_carbon" and node == "sink"
                        else 0.0
                    ),
                }
                for node in ("source", "sink")
            ],
        )
        if carrier == "captured_carbon" and slots > 1:
            write_csv(
                carrier_folder / "demand_yearly_variation.csv",
                [
                    {
                        "node": node,
                        "year": YEAR + s,
                        "demand_yearly_variation": (1.0 if s == 0 else 2.5),
                    }
                    for node in ("source", "sink")
                    for s in range(slots)
                ],
            )
        write_csv(
            carrier_folder / "availability_import.csv",
            [
                {
                    "node": node,
                    "availability_import": (
                        100 / HOURS
                        if carrier == "raw_emissions" and node == "source"
                        else 0.0
                    ),
                }
                for node in ("source", "sink")
            ],
        )

    capture = folder / "set_technologies/set_conversion_technologies/capture"
    attrs = technology_attributes(slots)
    attrs.update(
        {
            "reference_carrier": attribute(["captured_carbon"]),
            "input_carrier": attribute(["raw_emissions"]),
            "output_carrier": attribute(["captured_carbon"]),
            "conversion_factor": {"raw_emissions": attribute(1.0, "tonne/tonne")},
            "carbon_intensity_technology": attribute(0.0, "tonne/tonne"),
            "capex_specific_conversion": attribute(0.0, "Euro/(tonne/hour)"),
            "min_full_load_hours_fraction": attribute(0.0, "1"),
        }
    )
    write_yaml(capture / "attributes.yaml", attrs)
    write_csv(
        capture / "capacity_limit.csv",
        [
            {"node": "source", "capacity_limit": 100 / HOURS},
            {"node": "sink", "capacity_limit": 0.0},
        ],
    )
    addition_file(capture, float("inf"), slots)
    for technology in pipelines + ["truck"]:
        transport = folder / "set_technologies/set_transport_technologies" / technology
        size = SIZES.get(technology, 100.0)
        attrs = technology_attributes(slots, size)
        fixed_cost = (
            binary and technology != "truck" and specification["kind"] == "fixed_cost"
        )
        attrs.update(
            {
                "reference_carrier": attribute(["captured_carbon"]),
                "carbon_intensity_technology": attribute(0.0, "tonne/tonne/km"),
                "transport_loss_factor_linear": attribute(0.0, "1/km"),
                "distance": attribute(1.0, "km"),
                "capex_specific_transport": attribute(
                    0.0 if fixed_cost or technology == "truck" else 4.0 * HOURS,
                    "Euro/(tonne/hour)",
                ),
                "capex_per_distance_transport": attribute(
                    4.0 * size if fixed_cost else 0.0, "Euro/km"
                ),
                "opex_specific_variable": attribute(
                    8.0 if technology == "truck" else 1.0, "Euro/tonne"
                ),
            }
        )
        if technology in SIZES:
            attrs["capacity_addition_min"] = attribute(size / HOURS, "tonne/hour")
            attrs["capacity_addition_max"] = attribute(size / HOURS, "tonne/hour")
        write_yaml(transport / "attributes.yaml", attrs)
        write_csv(
            transport / "distance.csv",
            [{"edge": "source-sink", "distance": 1.0}],
        )
        addition_file(
            transport, size / HOURS if technology in SIZES else float("inf"), slots
        )
    for subset in ("set_storage_technologies", "set_retrofitting_technologies"):
        empty = folder / "set_technologies" / subset
        empty.mkdir(parents=True, exist_ok=True)
        (empty / ".gitkeep").touch()


def enumerate_hand_calculations():
    rows = []
    expectations = {}
    for name, specification in CASES.items():
        probabilities = specification["probabilities"]
        demands = [40.0, 100.0][: len(probabilities)]
        candidates = (
            range(101)
            if specification["kind"] == "continuous"
            else itertools.product((0, 1), repeat=2)
        )
        case_rows = []
        for candidate in candidates:
            if specification["kind"] == "continuous":
                capacity = float(candidate)
                builds = {"pipeline": "continuous"}
            else:
                builds = dict(zip(SIZES, candidate, strict=True))
                capacity = sum(SIZES[t] * g for t, g in builds.items())
            investment = 4.0 * capacity
            annual_capital = investment / len(probabilities)
            operating = [min(d, capacity) + 8 * max(d - capacity, 0) for d in demands]
            expected_operation = sum(
                p * c for p, c in zip(probabilities, operating, strict=True)
            )
            row = {
                "case": name,
                "builds": json.dumps(builds),
                "capacity_tonnes_per_year": capacity,
                "investment_EUR": investment,
                "annual_capital_EUR": annual_capital,
                "low_operation_EUR": operating[0],
                "high_operation_EUR": operating[1] if len(operating) > 1 else "",
                "expected_operation_EUR": expected_operation,
                "total_EUR": annual_capital + expected_operation,
            }
            case_rows.append(row)
        rows.extend(case_rows)
        best = min(case_rows, key=lambda r: r["total_EUR"])
        capacity = best["capacity_tonnes_per_year"]
        expectations[name] = {
            **specification,
            "demands": demands,
            "hand_optimum": best,
            "pipeline_flow_tonnes": [min(d, capacity) for d in demands],
            "truck_flow_tonnes": [max(d - capacity, 0) for d in demands],
        }
    write_csv(HAND_ROOT / "all_candidates.csv", rows)
    (HAND_ROOT / "expected_results.json").write_text(
        json.dumps(expectations, indent=2) + "\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hand-only",
        action="store_true",
        help="Recalculate annual-cost hand results without overwriting native inputs",
    )
    args = parser.parse_args()
    if not args.hand_only:
        for name, specification in CASES.items():
            build_case(name, specification)
    enumerate_hand_calculations()
    write_csv(
        HAND_ROOT / "input_hashes.csv",
        [
            {
                "file": str(p.relative_to(ROOT)),
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in sorted((ROOT / "cases").rglob("*"))
            if p.is_file()
        ],
    )
    print(
        f"Native inputs: {ROOT / 'cases'}; annual-cost hand calculations: {HAND_ROOT}"
    )
    print(
        "Annual hand optima: continuous 270; binary equal 270; "
        "binary high probability 288; deterministic control 280 EUR"
    )


if __name__ == "__main__":
    main()
