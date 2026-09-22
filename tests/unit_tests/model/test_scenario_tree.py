"""Focused tests for the stochastic scenario-tree service."""

import json
from copy import deepcopy

import pytest
import yaml

from zen_garden.model.scenario_tree import ScenarioTree


@pytest.fixture
def branching_tree():
    return {
        "node_id": 0,
        "year": 2023,
        "probability": 1.0,
        "children": [
            {
                "node_id": 1,
                "year": 2024,
                "probability": 1.0,
                "children": [
                    {
                        "node_id": 2,
                        "year": 2025,
                        "probability": 0.4,
                        "state": [
                            {"natural_gas": {"price_import": {"node_id_op": [10]}}}
                        ],
                    },
                    {"node_id": 3, "year": 2025, "probability": 0.6},
                ],
            }
        ],
    }


def test_paths_probabilities_and_node_local_state(branching_tree):
    tree = ScenarioTree(branching_tree, [2023, 2024, 2025])
    assert tree.nodes == (0, 1, 2, 3)
    assert tree.leaves == (2, 3)
    assert tree.path(2) == (0, 1, 2)
    assert tree.ancestors(3) == (0, 1)
    assert tree.ancestor_steps(3, 2) == 0
    assert tree.ancestor_steps(3, 3) is None
    assert tree.nodes_for_year(2025) == (2, 3)
    assert tree.probability(2) == 0.4
    assert tree.state_multiplier(2, "natural_gas", "price_import") == 10
    assert tree.state_multiplier(3, "natural_gas", "price_import") == 1
    assert tree.state_multiplier(1, "natural_gas", "price_import") == 1


def test_yaml_tree_file_and_legacy_json_fallback(tmp_path, branching_tree):
    yaml_file = tmp_path / "scenariotree.yaml"
    yaml_file.write_text(yaml.safe_dump(branching_tree))
    assert ScenarioTree.from_file(yaml_file, [2023, 2024, 2025]).leaves == (2, 3)

    yaml_file.unlink()
    json_file = tmp_path / "scenariotree.json"
    json_file.write_text(json.dumps(branching_tree))
    assert ScenarioTree.from_file(yaml_file, [2023, 2024, 2025]).leaves == (2, 3)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda data: data.update(node_id=1), "root node ID"),
        (
            lambda data: data["children"][0]["children"][1].update(node_id=4),
            "consecutive",
        ),
        (
            lambda data: data["children"][0]["children"][0].update(probability=0.3),
            "children of node 1",
        ),
        (
            lambda data: data["children"][0]["children"][0].update(year=2024),
            "expected 2025",
        ),
        (
            lambda data: data["children"][0]["children"][0].update(
                state=[{"natural_gas": {"price_import": {"node_id_op": ["bad"]}}}]
            ),
            "Invalid state factor",
        ),
    ],
)
def test_invalid_trees_are_rejected(branching_tree, change, message):
    invalid = deepcopy(branching_tree)
    change(invalid)
    with pytest.raises(ValueError, match=message):
        ScenarioTree(invalid, [2023, 2024, 2025])


def test_incomplete_path_is_rejected(branching_tree):
    branching_tree["children"][0]["children"] = []
    with pytest.raises(ValueError, match="stops before final year"):
        ScenarioTree(branching_tree, [2023, 2024, 2025])


def test_original_ms1_5_probability_pattern_is_rejected():
    tree = {
        "node_id": 0,
        "year": 2023,
        "probability": 1,
        "children": [
            {
                "node_id": 1,
                "year": 2024,
                "probability": 0.5,
                "children": [
                    {"node_id": 3, "year": 2025, "probability": 0.25},
                    {"node_id": 4, "year": 2025, "probability": 0.25},
                ],
            },
            {
                "node_id": 2,
                "year": 2024,
                "probability": 0.5,
                "children": [
                    {"node_id": 5, "year": 2025, "probability": 0.24},
                    {"node_id": 6, "year": 2025, "probability": 0.01},
                ],
            },
        ],
    }
    with pytest.raises(ValueError, match="children of node 2"):
        ScenarioTree(tree, [2023, 2024, 2025])
    tree["children"][1]["children"][0]["probability"] = 0.49
    assert sum(
        ScenarioTree(tree, [2023, 2024, 2025]).probability(n) for n in (3, 4, 5, 6)
    ) == pytest.approx(1.0)
