"""Two-stage value-of-the-stochastic-solution workflow."""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
from pathlib import Path

import yaml

from zen_garden.config import Config
from zen_garden.model.scenario_tree import ScenarioTree
from zen_garden.postprocess.results.results import Results
from zen_garden.workflow.runner import run


def _expected_value_tree(tree: ScenarioTree) -> dict:
    """Collapse one branching stage into a probability-averaged single path."""
    years = sorted({tree.node(node).year for node in tree.nodes})
    child = None
    for node_id, year in reversed(list(enumerate(years))):
        state = []
        for element, parameter in tree.state_parameters:
            factor = sum(
                tree.probability(node) * tree.state_multiplier(node, element, parameter)
                for node in tree.nodes_for_year(year)
            )
            if factor != 1:
                state.append({element: {parameter: {"node_id_op": [factor]}}})
        current = {"node_id": node_id, "year": year, "probability": 1.0}
        if state:
            current["state"] = state
        if child is not None:
            current["children"] = [child]
        child = current
    assert child is not None
    return child


def _objective(workflow) -> float:
    model = workflow.service_container.get("optimization_model")
    value = model.lp_model.objective.value
    if value is None:
        raise RuntimeError("VSS run did not produce an optimal objective")
    return float(value)


def _write_fixed_policy(
    expected_results: Results,
    expected_tree: ScenarioTree,
    recourse_tree: ScenarioTree,
    path: Path,
) -> None:
    """Map expected-value investment years to every corresponding tree node."""
    values = expected_results.first_scenario.get_values(
        "capacity_investment", rename_index=False
    )
    records = []
    for node in recourse_tree.nodes:
        matching = expected_tree.nodes_for_year(recourse_tree.node(node).year)
        if len(matching) != 1:
            raise ValueError("Expected-value tree must have one node per year")
        ev_node = matching[0]
        for (technology, capacity_type, location, source_node), value in values.items():
            if source_node != ev_node:
                continue
            records.append(
                {
                    "technology": str(technology),
                    "capacity_type": str(capacity_type),
                    "location": str(location),
                    "node_id": node,
                    "value": float(value),
                }
            )
    with path.open("w", encoding="utf-8") as stream:
        yaml.safe_dump({"investments": records}, stream, sort_keys=False)


def run_two_stage_vss(
    config: str | Path,
    folder_output: str | Path,
    log_level: str | int = logging.ERROR,
) -> dict[str, float]:
    """Solve RP, expected-value policy, and fixed-policy stochastic replay.

    This is defined only for trees with one branching node. All investment
    variables from the single-path expected-value solution are fixed in every
    matching calendar-year node of the original tree; operation remains free.
    The returned value is ``VSS = EEV - RP`` for a minimization problem.
    """
    config = Path(config)
    configuration = Config.from_file(config)
    if (
        configuration.analysis.objective != "total_cost"
        or configuration.analysis.sense != "min"
    ):
        raise ValueError("Two-stage VSS currently requires cost minimization")
    if not configuration.system.use_scenariotree:
        raise ValueError("Two-stage VSS requires a scenario tree")
    if not configuration.system.allow_investment:
        raise ValueError("Two-stage VSS requires investment to be enabled")
    dataset = Path(configuration.analysis.dataset)
    years = [
        configuration.system.reference_year
        + i * configuration.system.interval_between_years
        for i in range(configuration.system.optimized_years)
    ]
    recourse_tree = ScenarioTree.from_file(dataset / "scenariotree.yaml", years)
    branching = [
        node
        for node in recourse_tree.nodes
        if len(recourse_tree.node(node).children) > 1
    ]
    if len(branching) != 1:
        raise ValueError("Two-stage VSS requires exactly one branching node")

    output_root = Path(folder_output)
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(f"VSS output folder must be empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    rp_workflow = run(
        config=config,
        folder_output=output_root / "recourse",
        investment_mode="optimize",
        log_level=log_level,
    )
    rp = _objective(rp_workflow)

    with tempfile.TemporaryDirectory(prefix="zen-expected-value-") as temp_dir:
        expected_dataset = Path(temp_dir) / "expected_value_base_case"
        shutil.copytree(dataset, expected_dataset)
        expected_tree_data = _expected_value_tree(recourse_tree)
        with (expected_dataset / "scenariotree.yaml").open(
            "w", encoding="utf-8"
        ) as stream:
            yaml.safe_dump(expected_tree_data, stream, sort_keys=False)
        expected_tree = ScenarioTree(expected_tree_data, years)
        ev_workflow = run(
            config=config,
            dataset=expected_dataset,
            folder_output=output_root / "expected_value",
            investment_mode="optimize",
            log_level=log_level,
        )
        ev = _objective(ev_workflow)
        ev_results = Results(output_root / "expected_value" / expected_dataset.name)
        fixed_file = output_root / "fixed_investments.yaml"
        _write_fixed_policy(ev_results, expected_tree, recourse_tree, fixed_file)

    eev_workflow = run(
        config=config,
        folder_output=output_root / "fixed_replay",
        investment_mode="fixed",
        fixed_investments_file=fixed_file,
        log_level=log_level,
    )
    eev = _objective(eev_workflow)
    summary = {"RP": rp, "EV": ev, "EEV": eev, "VSS": eev - rp}
    with (output_root / "vss.json").open("w", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2)
    return summary
