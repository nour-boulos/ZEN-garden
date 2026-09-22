"""Checks that tree nodes, not numeric IDs, control input and history."""

from types import SimpleNamespace

import pandas as pd

from zen_garden.config import Config
from zen_garden.elements.technology.constraints import (
    TechnologyConstructionTimeConstraint,
)
from zen_garden.elements.technology.constraints.technology_constraint import (
    TechnologyConstraint,
)
from zen_garden.input.element_data_loader import ElementDataLoader
from zen_garden.input.time_series_aggregation import TimeSeriesAggregation
from zen_garden.model.scenario_tree import ScenarioTree
from zen_garden.model.schema import ModelSchema


def _schema():
    config = Config()
    config.system.reference_year = 2023
    config.system.optimized_years = 3
    config.system.unaggregated_time_steps_per_year = 2
    schema = ModelSchema(config)
    schema.scenario_tree = ScenarioTree(
        {
            "node_id": 0,
            "year": 2023,
            "probability": 1,
            "children": [
                {
                    "node_id": 1,
                    "year": 2024,
                    "probability": 1,
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
        },
        [2023, 2024, 2025],
    )
    return schema


def test_calendar_year_rows_expand_to_both_sibling_nodes():
    schema = _schema()
    loader = object.__new__(ElementDataLoader)
    loader.model_schema = schema
    loader.index_names = schema.config.analysis.header_data_inputs
    input_data = pd.DataFrame(
        {"node": ["DE", "DE"], "year": [2023, 2025], "price_import": [10.0, 30.0]}
    )
    converted = loader._convert_real_to_generic_time_indices(
        input_data, ["set_nodes", "set_years"], "price_import", ["node", "year"]
    )
    values = dict(zip(converted.year, converted.price_import, strict=True))
    assert values == {0: 10.0, 1: 20.0, 2: 30.0, 3: 30.0}


def test_hourly_state_factor_affects_only_its_node():
    schema = _schema()
    aggregator = object.__new__(TimeSeriesAggregation)
    aggregator.model_schema = schema
    aggregator.time_steps = SimpleNamespace(
        decode_time_step=lambda node, kind: [node * 2, node * 2 + 1],
        encode_time_step=lambda hours, time_step_type: hours,
    )
    hours = pd.MultiIndex.from_product([["DE"], range(8)], names=["node", "time"])
    values = pd.Series(2.0, index=hours)
    changed = aggregator.apply_scenario_tree_state(
        SimpleNamespace(name="natural_gas"), "price_import", values, "time"
    )
    assert changed.loc[("DE", 4)] == 20.0
    assert changed.loc[("DE", 5)] == 20.0
    assert changed.loc[("DE", 6)] == 2.0


def test_construction_and_lifetime_follow_parent_path():
    schema = _schema()
    parameters = SimpleNamespace(
        dict_parameters=SimpleNamespace(
            construction_time={"tech": 1}, lifetime={"tech": 2}
        )
    )
    constructor = SimpleNamespace(
        model_schema=schema,
        config=schema.config,
        optimization_model=SimpleNamespace(parameters=parameters),
    )
    assert (
        TechnologyConstructionTimeConstraint._get_investment_time_step(
            constructor, "tech", 3
        )
        == 1
    )
    assert TechnologyConstraint.get_lifetime_range(constructor, "tech", 3) == (1, 3)
    assert 2 not in TechnologyConstraint.get_lifetime_range(constructor, "tech", 3)
