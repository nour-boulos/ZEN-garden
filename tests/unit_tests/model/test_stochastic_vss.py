"""Fixed-investment and three-run VSS checks."""

import json
from pathlib import Path

import pytest
import yaml

from zen_garden import Results, run
from zen_garden.model.fixed_investments import FixedInvestments
from zen_garden.workflow.vss import run_two_stage_vss

MS_CONFIG = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "MS_Dummy_Model"
    / "MS1_4"
    / "config.yaml"
)


def test_fixed_policy_rejects_bad_values():
    record = {
        "technology": "heat_pump",
        "capacity_type": "power",
        "location": "DE",
        "node_id": 0,
        "value": 1.0,
    }
    with pytest.raises(ValueError, match="Duplicate"):
        FixedInvestments([record, record], (0,))
    with pytest.raises(ValueError, match="Invalid"):
        FixedInvestments([{**record, "value": -1.0}], (0,))


def test_two_stage_vss_uses_fixed_replay(tmp_path):
    if not MS_CONFIG.exists():
        pytest.skip("Local data/MS_Dummy_Model fixture is not available")
    result = run_two_stage_vss(MS_CONFIG, tmp_path / "vss")
    assert result["RP"] == pytest.approx(2516.3628620, rel=1e-5)
    assert result["EV"] == pytest.approx(2776.0280148, rel=1e-5)
    assert result["EEV"] == pytest.approx(result["EV"], rel=1e-8)
    assert result["VSS"] == pytest.approx(259.6651529, rel=1e-5)
    assert result["EEV"] >= result["RP"]
    policy = yaml.safe_load((tmp_path / "vss" / "fixed_investments.yaml").read_text())
    assert policy["investments"]
    assert {record["node_id"] for record in policy["investments"]} == {0, 1, 2, 3}
    assert json.loads((tmp_path / "vss" / "vss.json").read_text()) == result

    # The EV policy happens to choose zero storage energy. Exercise the
    # separate energy equality with a nonzero prescribed investment too.
    storage_record = next(
        record
        for record in policy["investments"]
        if record["technology"] == "natural_gas_storage"
        and record["capacity_type"] == "energy"
        and record["location"] == "DE"
        and record["node_id"] == 2
    )
    storage_record["value"] = 0.1
    altered_policy = tmp_path / "nonzero_storage_policy.yaml"
    altered_policy.write_text(yaml.safe_dump(policy))
    replay_output = tmp_path / "nonzero_storage_replay"
    run(
        config=MS_CONFIG,
        folder_output=replay_output,
        investment_mode="fixed",
        fixed_investments_file=altered_policy,
    )
    replay = Results(replay_output / "1_4_base_case")
    investments = replay.first_scenario.get_values(
        "capacity_investment", rename_index=False
    )
    assert investments.loc[("natural_gas_storage", "energy", "DE", 2)] == pytest.approx(
        0.1
    )
    with pytest.raises(FileExistsError, match="must be empty"):
        run_two_stage_vss(MS_CONFIG, tmp_path / "vss")
