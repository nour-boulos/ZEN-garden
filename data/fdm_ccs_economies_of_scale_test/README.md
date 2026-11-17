# CCS pipeline-size MILP benchmark

## Verified outcome

The repaired FDM implementation passes this discrete pipeline investment benchmark. All seven native MILP cases match the independent hand calculations, including both probability-weighted deterministic controls. Pipeline capacity is now linked to its build binary, subsequent additions remain zero, and shared annual capital is counted once. The only production change in this checkpoint is the approved FDM maximum-addition repair. The objective and annual-CAPEX accounting were not edited.

The original failing results are preserved in [checkpoint 20](../../checkpoints/stochastic_fixed_investment/20_binary_economies_of_scale/REPORT.md). Current evidence is in [checkpoint 21](../../checkpoints/stochastic_fixed_investment/21_binary_capacity_link_repair/REPORT.md).

Validation used baseline commit `ad4bdfcee538aec810fb16e85ecd43ab58f6c828` on `feature/fdm-fixed-investment-v3` plus the binary-link repair included with this benchmark. The original pre-commit validation snapshot is saved locally as [tested_worktree.patch](../../checkpoints/stochastic_fixed_investment/21_binary_capacity_link_repair/tested_worktree.patch).

## Small network and units

There are two nodes, `source` and `sink`, joined by one 1 km route. A free conversion technology at the source converts raw emissions to captured carbon at a 1:1 ratio. Captured-carbon demand is at the sink. Pipelines and trucks carry the same captured-carbon carrier. Direct captured-carbon imports and all shedding are prohibited. Raw-emissions availability is sufficient for the largest demand of 100 tonnes/year.

| Technology | Capacity (tonnes/year) | Upfront construction fee (€) | Annual capital (€) | Operation (€/tonne) |
| --- | --- | --- | --- | --- |
| Small pipeline | 60 | 1200 | 65.732083 | 1 |
| Large pipeline | 100 | 1600 | 87.642777 | 1 |
| Trucks | Flexible | 0 | 0 | 8 |
| Capture | Up to 100 | 0 | 0 | 0 |

The large pipeline costs €16 per unit of annual capacity, compared with €20 for the small pipeline. Its unit construction cost is 20% lower. Each size has minimum addition equal to maximum addition. In the intended catalogue formulation, its build binary chooses either zero capacity or the full size. The native model allows both pipeline sizes to be built in parallel, so the hand calculation includes that choice as well; no extra exclusivity constraint was introduced.

Input capacities and constant flows use tonnes/hour: an annual capacity of 60 becomes `60/8760`, and 100 becomes `100/8760`. Time aggregation produces one operating step with duration 8760 hours in every model slot. The explicit `distance.csv` is 1 km. `double_capex_transport: true` enables a zero capacity-specific coefficient plus a distance-based fixed construction fee, which is €1200/km or €1600/km times the installation binary and the 1 km distance. The numbers above are total overnight fees, before annualization.

## One physical year, alternative operating futures

The real representative year is 2026. Demand is 40 tonnes/year in the low future and 100 in the high future. FDM encodes these alternative futures as fictitious model years. All capacity additions are permitted only in the first slot; the maximum addition is zero in all later slots. FDM is enabled and the scenario-tree option is disabled. All technologies have physical lifetime and depreciation time of 50 years, longer than the two or four fictitious slots.

The discount rate is 5%. The annuity factor is `0.05 / (1 - 1.05**(-50)) = 0.054776735486`. A built small pipeline therefore contributes €65.732083/year and a built large pipeline contributes €87.642777/year. These are annual financing charges for this representative-year objective. There is no second upfront payment added to the objective and no discount between alternative futures. Current production code includes shared annual capital once, in the first slot, and probability-weights operating costs.

## Independent hand calculation

For each of the four binary build choices, total available pipeline capacity is `K`. In a future with demand `d`, the cheapest operation costs `min(d,K) + 8*max(d-K,0)`: use the pipeline first at €1/tonne and trucks for the remainder at €8/tonne. Annual total cost is the common annual capital charge plus the probability-weighted operating cost.

| Build choice | Capacity (t/year) | Upfront (€) | Annual capital (€) | Expected operation: equal (€) | Total: equal (€) | Expected operation: rare high (€) | Total: rare high (€) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Trucks only | 0 | 0.00 | 0.000000 | 560.00 | 560.000000 | 344.00 | 344.000000 |
| Small pipeline | 60 | 1200.00 | 65.732083 | 210.00 | 275.732083 | 57.00 | 122.732083 |
| Large pipeline | 100 | 1600.00 | 87.642777 | 70.00 | 157.642777 | 43.00 | 130.642777 |
| Both pipelines | 160 | 2800.00 | 153.374859 | 70.00 | 223.374859 | 43.00 | 196.374859 |

With equally likely futures, the large pipeline wins: `€87.642777 + 0.5*€40 + 0.5*€100 = €157.642777/year`. With 5% probability of high demand, the small pipeline wins: low demand costs €40 to transport; high demand costs `60*€1 + 40*€8 = €380`; expected operation is `0.95*€40 + 0.05*€380 = €57`; annual total is `€65.732083 + €57 = €122.732083`.

All four choices for every case are in [all_build_choices.csv](hand_calculations/all_build_choices.csv). Per-future costs are retained in its `operation_by_future_EUR` column.

## Deterministic controls

The primary deterministic controls use normal ZEN-garden with `use_stochastic_fdm: false`, one model year, and the probability-weighted demand. Equal probabilities give `0.5*40 + 0.5*100 = 70` tonnes/year. The rare-high case gives `0.95*40 + 0.05*100 = 43` tonnes/year. They are **expected-demand optimizations**, not optimizations of each future separately. The extra 40- and 100-tonne controls are supplementary checks.

The expected-demand control and the stochastic problem need not have equal objective values. For example, the small pipeline carries all 43 tonnes in the expected-demand control, giving €108.732083/year. In the actual high future it needs trucks for 40 tonnes, so its correct stochastic cost is €122.732083/year. In this benchmark the optimal build happens to match its expected-demand control in both probability cases; that need not hold for other inputs.

## Duplicated-futures check

`stochastic_equal_duplicated` splits each original 50% future into two identical 25% copies: demand `[40,100,40,100]` with probabilities `[0.25,0.25,0.25,0.25]`. This changes the representation without changing the uncertainty. A correct result should preserve the optimum cost. It is a bookkeeping check for costs or weights that accidentally depend on the number of fictitious slots.

After the repair, both the original and duplicated-future models choose the large pipeline and return €157.642777/year, matching their hand optima. Both include a positive annual capital charge of €87.642777 exactly once, plus €70 expected operation. Unlike the earlier failing solves, this comparison now exercises positive capital. Generated coefficients also confirm capital weight 1 initially and 0 later, with operating weights matching probabilities.

## Native results

| Case | Chosen pipeline (tonnes/year) | Hand total (€/year) | Model total (€/year) | Annual capital (€) | Expected operation (€) | Result |
| --- | --- | --- | --- | --- | --- | --- |
| stochastic_equal | 100 | 157.642777 | 157.642777 | 87.642777 | 70.000000 | PASS |
| stochastic_rare_high | 60 | 122.732083 | 122.732083 | 65.732083 | 57.000000 | PASS |
| stochastic_equal_duplicated | 100 | 157.642777 | 157.642777 | 87.642777 | 70.000000 | PASS |
| deterministic_low | 60 | 105.732083 | 105.732083 | 65.732083 | 40.000000 | PASS |
| deterministic_high | 100 | 187.642777 | 187.642777 | 87.642777 | 100.000000 | PASS |
| deterministic_expected_equal | 100 | 157.642777 | 157.642777 | 87.642777 | 70.000000 | PASS |
| deterministic_expected_rare_high | 60 | 108.732083 | 108.732083 | 65.732083 | 43.000000 | PASS |

All seven solves terminate optimally. The two-slot FDM models have four build binaries, and the duplicated four-slot model has eight. Active binaries are integral within solver tolerance. Every chosen first-slot pipeline has its catalogue capacity and pays its fee. Later build binaries and additions equal zero, capacities remain shared across futures, and all demand is captured and delivered without shedding. In the rare-high case, the small pipeline carries 60 tonnes and trucks carry the remaining 40 tonnes in the high-demand future.

## Reproduce and inspect

From the repository root:

```sh
.venv/bin/python -m data.fdm_ccs_economies_of_scale_test.check_milp
```

The runner builds missing case folders and checks the loaded native parameters before solving. It uses the existing small dataset builder in `data/fdm_ccs_binary_test/build_dataset.py`. It never injects test constraints, changes variable bounds or alters the native objective. Existing case folders are reused and audited. To rebuild from scratch, rename this benchmark's `cases` folder first; do not remove unrelated datasets.

The output folder defaults to `checkpoints/stochastic_fixed_investment/21_binary_capacity_link_repair`. Use `--output PATH` to select another output folder and preserve previous evidence. The current run exits 0: all 502 audit checks pass. Exit status 1 indicates at least one input, solver, model or intended-design acceptance check failed; inspect the saved summary and logs.

### Local evidence

The following reports and generated outputs are local artifacts, excluded from Git. The runner creates the case inputs, hand-calculation files and current MILP output when executed. Historical checkpoint reports and the separate unit/continuous logs are available in the original workspace.

- [Full repair report](../../checkpoints/stochastic_fixed_investment/21_binary_capacity_link_repair/REPORT.md)
- [All-case comparison](../../checkpoints/stochastic_fixed_investment/21_binary_capacity_link_repair/comparison.csv)
- [Before/after comparison](../../checkpoints/stochastic_fixed_investment/21_binary_capacity_link_repair/before_after_comparison.csv)
- [Every audit check](../../checkpoints/stochastic_fixed_investment/21_binary_capacity_link_repair/checks.csv)
- [Complete native solver console](../../checkpoints/stochastic_fixed_investment/21_binary_capacity_link_repair/native_milp_runs.log)
- [All 37 unit tests](../../checkpoints/stochastic_fixed_investment/21_binary_capacity_link_repair/unit_tests.log)
- [Continuous-investment regression results](../../checkpoints/stochastic_fixed_investment/21_binary_capacity_link_repair/continuous_cases/summary.json)
- [Equal-probability capacities and binaries](../../checkpoints/stochastic_fixed_investment/21_binary_capacity_link_repair/stochastic_equal/capacities_and_binaries.csv)
- [Rare-high operation by future](../../checkpoints/stochastic_fixed_investment/21_binary_capacity_link_repair/stochastic_rare_high/annual_operations.csv)
- [Equal-probability generated binary coefficients](../../checkpoints/stochastic_fixed_investment/21_binary_capacity_link_repair/stochastic_equal/binary_equation_trace.csv)
- [Equal-probability generated objective coefficients](../../checkpoints/stochastic_fixed_investment/21_binary_capacity_link_repair/stochastic_equal/objective_equation_trace.csv)
- [Case input hashes](hand_calculations/input_hashes.csv)

Every case output folder also contains loaded parameter CSVs, all variable solutions as CSV, a solution NetCDF, the solved native LP and constraint term exports. Per-case `run.log` captures Python logging; native solver console output is in the complete run log above. Original failure evidence is preserved in checkpoint 20.

The production repair, unit regressions, this README and `check_milp.py` are versioned. Generated case inputs, hand-calculation files and checkpoint outputs remain excluded from Git. Source hashes and the tracked diff were verified unchanged during the final native solves, after the repair was applied. The large uploaded dataset was not solved.
