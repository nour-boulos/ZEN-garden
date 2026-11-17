# CCS test of FDM shared investment and pipeline build binaries

**Verified result (17 November 2026):** the current FDM port solves the continuous
CCS case correctly, but does not enforce the intended discrete pipeline builds.
In the equal-probability fixed-build-cost case it returns **EUR 70**, rather than
the independent catalogue optimum **EUR 450**. Both pipeline build binaries are
zero while their capacity is positive. No model formulation was changed to run
these tests.

## Status and result files

This checkpoint preserves the literal FDM port before correcting annual-capital
counting or pipeline binaries. See the [feature documentation](../../docs/files/zen_garden_in_detail/stochastic_fdm.rst)
for the equations, known limitations and planned correction order. After running
the checks, inspect `capacity_and_binaries.csv` and `comparison.csv` under
`checkpoints/stochastic_fixed_investment/09_ccs_binary_test/`.

## Network and input choices

There are two nodes (`source`, `sink`) and one directed corridor of exactly 1 km.
A free, 1:1 conversion technology turns raw emissions into captured carbon at
source. Pipelines and trucks transport captured carbon to a sink demand. There
is no separate storage technology: the demand represents the required delivery.
Raw emissions can be imported only at source; captured carbon cannot be
imported. Losses, capture costs, truck capital costs and fixed operating costs
are zero. Pipeline operation costs EUR 1/tonne; truck operation costs EUR 8/tonne.

The physical problem covers one year. The FDM workaround encodes its low- and
high-demand futures as two fictitious model-year slots, labelled 2026 and 2027.
Demand is 40 or 100 tonnes; only this demand changes between futures. Raw supply
availability and all technology characteristics remain the same. Both futures
are optimized in one model. Investment is optimized in slot 0 and later additions
are prohibited with a zero `capacity_addition_max`.

Each slot contains 8760 hours represented by one aggregated operating timestep.
Inputs for flow and capacity are in tonnes/hour, so a capacity of 60 tonnes/year
is entered as `60/8760`. A EUR 4 investment coefficient per tonne/year is entered
as `4*8760` EUR/(tonne/hour). Distance is explicitly provided in `distance.csv`;
this avoids relying on the geographic distance calculated from node coordinates.

FDM cases use zero discount, lifetime 2 and depreciation 2. The existing annuity
is therefore 1/2, and the two capital charges sum to the upfront investment once.
The one-slot deterministic control uses lifetime and depreciation 1.

All carriers have `price_shed_demand: .inf`. FDM cases also set
`expected_loss_of_load: 0`. Solved shedding is zero in every case. The original
FDM reliability factor 0.5 remains unchanged and has no effect with zero shedding.

## Cases

| Folder under `cases/` | Intended investment choice | Probabilities | Hand optimum EUR | Actual EUR |
| --- | --- | --- | ---: | ---: |
| `continuous_equal` | Continuous pipeline capacity | 0.5 / 0.5 | 440 | 440 |
| `binary_capacity_cost_equal` | 60- or 100-tonne/year builds; cost per capacity | 0.5 / 0.5 | 450 | 440 |
| `binary_fixed_cost_equal` | 60- or 100-tonne/year builds; fixed build cost | 0.5 / 0.5 | 450 | 70 |
| `binary_fixed_cost_high_probability` | Same fixed-cost builds | 0.2 / 0.8 | 488 | 88 |
| `deterministic_binary_control` | Same fixed-cost builds, demand 40 known | 1.0 | 280 | 280 |

Each binary pipeline is a separate transport technology. Its minimum and
first-slot maximum additions both equal its catalogue size: 60 or 100 tonnes/year.
The capacity-cost variant charges EUR 4 per unit of annual capacity. The
fixed-build-cost variant uses `double_capex_transport: true`, zero specific
capacity cost, and fixed distance costs of EUR 240/km or EUR 400/km. At a 1 km
distance these are EUR 240 and EUR 400 per build. Both variants have the same
costs when the catalogue size is enforced correctly.

The native model permits both pipeline technologies to be built in parallel.
The hand enumeration therefore includes none, small, large and both. It does not
assume an extra either/or constraint. Building both is more expensive than the
optimal choice in every hand-calculated binary case.

## Independent calculation

For installed pipeline capacity K, operation at demand D costs:

```text
operation(K,D) = min(K,D) + 8*max(D-K,0)
expected total = upfront investment + sum(probability * operation)
```

At equal probabilities, the intended 60-tonne/year pipeline costs:

```text
investment:    240
low operation: 40
high operation: 60 + 8*40 = 380
total:         240 + 0.5*40 + 0.5*380 = 450 EUR
```

The alternatives cost EUR 560 (trucks only), EUR 470 (large pipeline) and EUR 710
(both pipelines). When high demand has probability 0.8, the large pipeline wins
at EUR `400 + 0.2*40 + 0.8*100 = 488`.

For continuous investment the minimum is K=40, at EUR
`160 + 0.5*40 + 0.5*(40 + 8*60) = 440`.

After generation, all candidates and expected flows are saved locally in
`hand_calculations/all_candidates.csv` and `hand_calculations/expected_results.json`.

## Reproduction and saved outputs

From a fresh source checkout, generate the five native input folders once:

```sh
.venv/bin/python -m data.fdm_ccs_binary_test.build_dataset
```

The generator refuses to overwrite existing case folders. If they already exist,
proceed directly to the checks. From the repository root, run:

```sh
.venv/bin/python -m data.fdm_ccs_binary_test.run_checks
```

**Expected exit code on the tested source is 1.** This indicates failed
catalogue/benchmark checks, not a solver failure. All five native models reach
an optimal solution to their actual equations. The runner adds no model
constraints, bounds or objectives and uses the ordinary v3 `OptimizationStep.solve`
method with its existing cleanup behavior.

Each case output folder under
`checkpoints/stochastic_fixed_investment/09_ccs_binary_test/`
contains a solved LP model, all solved variables as CSV and NetCDF, loaded input
tables, native constraint terms, annual operations, capacities, binary decisions,
and the case summary. The aggregate log contains the HiGHS solver output.
Full checks are in `checks.csv`, and costs are in `comparison.csv`.

`build_dataset.py` creates the five native input folders and independent hand
calculations. It refuses to overwrite existing case folders. Its final output
was rebuilt in a temporary folder and verified identical to all 140 saved native
input files. Input hashes are generated in `hand_calculations/input_hashes.csv`.

The two Python scripts and this README are deliberately versioned. Generated
datasets, hand tables and checkpoint files remain local and ignored by Git.
No uploaded reference data is required. The original
`data/stochastic_fixed_investment_test` dataset was left unchanged.
