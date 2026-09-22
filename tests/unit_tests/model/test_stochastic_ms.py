"""End-to-end regression checks for the local MS dummy model fixtures."""

import logging
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from zen_garden import Results, run
from zen_garden.model.scenario_tree import ScenarioTree

MS_ROOT = Path(__file__).resolve().parents[3] / "data" / "MS_Dummy_Model"
EXPECTED_OBJECTIVES = {
    "MS1_0": 2608.9425551,
    "MS1_1": 2608.9425551,
    "MS1_2": 3010.5740567,
    "MS1_3": 2608.9425551,
    "MS1_4": 2516.3628620,
    "MS1_5": 27539.3346419,
}


def test_ms_source_inputs_use_yaml():
    if not MS_ROOT.exists():
        pytest.skip("Local data/MS_Dummy_Model fixture is not available")
    json_inputs = [
        path for path in MS_ROOT.rglob("*.json") if "outputs" not in path.parts
    ]
    yaml_inputs = [
        path for path in MS_ROOT.rglob("*.yaml") if "outputs" not in path.parts
    ]
    assert not json_inputs
    assert len(yaml_inputs) == 79


@pytest.fixture(scope="module")
def ms_results(tmp_path_factory):
    """Solve each MS case once with a portable solver and isolated outputs."""
    if not (MS_ROOT / "MS1_0" / "config.yaml").exists():
        pytest.skip("Local data/MS_Dummy_Model fixture is not available")
    output_root = tmp_path_factory.mktemp("stochastic_ms")
    results = {}
    for case in EXPECTED_OBJECTIVES:
        case_number = case[-1]
        output = output_root / case
        workflow = run(
            config=MS_ROOT / case / "config.yaml",
            folder_output=output,
            log_level=logging.ERROR,
        )
        assert workflow is not None
        model = workflow.service_container.get("optimization_model")
        objective = model.lp_model.objective.value
        assert objective is not None
        result_path = output / f"1_{case_number}_base_case"
        results[case] = (objective, Results(result_path), result_path)
    return results


@pytest.mark.parametrize("case", EXPECTED_OBJECTIVES)
def test_ms_objective_and_tree_persistence(ms_results, case):
    objective, results, output = ms_results[case]
    assert objective == pytest.approx(EXPECTED_OBJECTIVES[case], rel=1e-5)
    scenario = results.first_scenario
    if case == "MS1_0":
        assert scenario.scenario_tree is None
        assert not (output / "scenariotree.json").exists()
        return
    tree = scenario.scenario_tree
    assert tree is not None
    assert (output / "scenariotree.json").exists()
    assert results.get_years() == [2023, 2024, 2025]
    assert len(scenario.node_metadata) == len(tree.nodes)
    node_cost = scenario.get_total("net_present_cost")
    assert node_cost.index.name == "node_id"
    assert list(node_cost.index) == list(tree.nodes)
    expected = sum(node_cost[node] * tree.probability(node) for node in tree.nodes)
    assert objective == pytest.approx(expected, rel=1e-8)
    assert scenario.get_expected_total("net_present_cost") == pytest.approx(objective)
    assert list(
        scenario.get_path_total("net_present_cost", tree.leaves[-1]).index
    ) == list(tree.path(tree.leaves[-1]))


def test_ms_single_path_equivalence(ms_results):
    objective_0, results_0, _ = ms_results["MS1_0"]
    objective_1, results_1, _ = ms_results["MS1_1"]
    assert objective_1 == pytest.approx(objective_0, rel=1e-8)
    capacity_0 = results_0.first_scenario.get_values("capacity_investment")
    capacity_1 = results_1.first_scenario.get_values("capacity_investment")
    np.testing.assert_allclose(capacity_0.values, capacity_1.values, rtol=1e-6)


def test_ms_node_local_gas_prices(ms_results):
    for case, expected in {
        "MS1_2": {0: 1.0, 1: 1.0, 2: 10.0},
        "MS1_4": {0: 1.0, 1: 0.8, 2: 1.0, 3: 10.0},
        "MS1_5": {0: 1.0, 1: 1.0, 2: 1.0, 3: 0.5, 4: 0.4, 5: 1.0, 6: 100.0},
    }.items():
        _, results, output = ms_results[case]
        tree = results.first_scenario.scenario_tree
        assert tree is not None
        assert {
            node: tree.state_multiplier(node, "natural_gas", "price_import")
            for node in tree.nodes
        } == expected
        with xr.open_dataset(output / "parameters.nc") as parameters:
            price = parameters["price_import"].sel(
                set_carriers="natural_gas", set_nodes="DE"
            )
            hours_per_year = 96
            base = float(price.sel(set_time_steps_operation=0))
            for node, factor in expected.items():
                observed = float(
                    price.sel(set_time_steps_operation=node * hours_per_year)
                )
                assert observed == pytest.approx(base * factor)


def test_ms_branching_and_corrected_probability(ms_results):
    tree_3 = ms_results["MS1_3"][1].first_scenario.scenario_tree
    assert tree_3 is not None
    assert [tree_3.probability(node) for node in tree_3.leaves] == [0.2, 0.8]
    assert tree_3.path(2) == (0, 1, 2)
    assert tree_3.path(3) == (0, 1, 3)
    tree_5 = ms_results["MS1_5"][1].first_scenario.scenario_tree
    assert tree_5 is not None
    assert tree_5.probability(5) == 0.49
    assert sum(tree_5.probability(node) for node in tree_5.leaves) == pytest.approx(1)
    assert tree_5.path(5) == (0, 2, 5)
    assert tree_5.path(6) == (0, 2, 6)
    source_tree = ScenarioTree.from_file(
        MS_ROOT / "MS1_5" / "1_5_base_case" / "scenariotree.yaml",
        [2023, 2024, 2025],
    )
    assert source_tree.probability(5) == 0.49
    investment = ms_results["MS1_5"][1].first_scenario.get_values(
        "capacity_investment", rename_index=False
    )
    assert investment.loc[("heat_pump", "power", "DE", 6)] > 0
    assert investment.loc[("heat_pump", "power", "DE", 5)] == pytest.approx(0)
