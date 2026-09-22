"""An existing v3 emissions-budget case on an identical-futures tree."""

import logging
import shutil
from pathlib import Path

import numpy as np
import pytest
import yaml

from zen_garden import Results, run

TESTCASES = Path(__file__).resolve().parents[2] / "testcases"


def test_upstream_emissions_budget_on_two_branch_tree(tmp_path):
    source = TESTCASES / "test_1h"
    baseline_output = tmp_path / "baseline"
    tree_output = tmp_path / "tree_output"
    baseline = run(
        config=TESTCASES / "config.yaml",
        dataset=source,
        folder_output=baseline_output,
        log_level=logging.ERROR,
    )
    baseline_objective = baseline.service_container.get(
        "optimization_model"
    ).lp_model.objective.value
    target = tmp_path / "tree_case"
    shutil.copytree(source, target)
    system_file = target / "system.yaml"
    system = yaml.safe_load(system_file.read_text())
    system["use_scenariotree"] = True
    system_file.write_text(yaml.safe_dump(system))
    (target / "scenariotree.yaml").write_text(
        yaml.safe_dump(
            {
                "node_id": 0,
                "year": 2022,
                "probability": 1,
                "children": [
                    {"node_id": 1, "year": 2023, "probability": 0.4},
                    {"node_id": 2, "year": 2023, "probability": 0.6},
                ],
            }
        )
    )
    branched = run(
        config=TESTCASES / "config.yaml",
        dataset=target,
        folder_output=tree_output,
        log_level=logging.ERROR,
    )
    branched_objective = branched.service_container.get(
        "optimization_model"
    ).lp_model.objective.value
    assert branched_objective == pytest.approx(baseline_objective, rel=1e-7)
    results = Results(tree_output / target.name)
    cumulative = results.first_scenario.get_values(
        "carbon_emissions_cumulative", rename_index=False
    )
    assert cumulative.loc[1] == pytest.approx(cumulative.loc[2])
    assert np.isfinite(cumulative.loc[1])
