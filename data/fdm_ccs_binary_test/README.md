# Small CCS cases for FDM cost and pipeline build checks

The current continuous case uses one shared annual capital charge plus expected
annual operation. It chooses **100 tonnes/year** of pipeline capacity at an
annual total of **EUR 270**. The pipeline's upfront investment is EUR 400, its
annual charge is EUR 200, and expected operation is EUR 70.

The original port and its cost/binary failures are preserved in commit
`88447656`. See the [feature guide](../../docs/files/zen_garden_in_detail/stochastic_fdm.rst)
for the current capital correction. Pipeline binary equations are unchanged;
the native binary cases are reserved for the next step and have not been
retested with the corrected accounting in this checkpoint.

## Network and units

The network has source, sink and one directed 1 km corridor. Free 1:1 capture
converts raw emissions into captured carbon at source. Pipelines and trucks
transport it to a sink demand of 40 or 100 tonnes/year. The futures are equally
likely except in the case explicitly using high-demand probability 0.8.
Raw supply availability and technology characteristics stay constant.

Captured-carbon imports and all exports are prohibited. Demand shedding has
infinite price and the FDM loss threshold is zero. Capture costs, truck capital,
transport losses and fixed operation are zero. Pipeline operation costs
EUR 1/tonne and truck operation EUR 8/tonne.

Each operating future has 8760 hours represented by one aggregated timestep.
Native flow/capacity inputs are tonnes/hour. Annual throughput capacity 100 is
therefore entered as `100/8760`. The upfront capacity quote is EUR 4 per unit of
annual throughput, entered as `4*8760` EUR/(tonne/hour). Explicit `distance.csv`
files set each route to 1 km.

The two-slot FDM fixtures retain zero discount and lifetime/depreciation 2.
Their annuity is 1/2. The correction includes one such annual charge rather than
summing it over both futures. The single-slot deterministic control has
lifetime/depreciation 1. The separate capital-scaling benchmark uses 5% and
50-year financial inputs, independently of the number of futures.

## Cases and hand accounting

The `continuous_equal` case permits continuous pipeline capacity. The binary
fixtures provide separate `pipeline_small` and `pipeline_large` technologies
with sizes 60 and 100 tonnes/year. Their minimum and first-slot maximum additions
are both set to those sizes. Later additions are zero.

Capacity-priced pipelines cost EUR 4 per unit of annual capacity upfront.
Fixed-build variants use `double_capex_transport: true`, zero capacity price,
and EUR 240/km or EUR 400/km fixed build prices. At 1 km these are upfront
charges EUR 240 and EUR 400. The native model allows both pipelines in parallel,
so the hand enumeration includes neither, small, large and both.

For capacity K and demand D, operation costs
`min(K,D) + 8*max(D-K,0)`. At zero discount with the two-year financial life,
the annual capital charge is half the upfront cost. The expected total is that
single annual charge plus probability-weighted operation.

For continuous capacity K=100 this is EUR 200 capital plus EUR 70 operation,
giving EUR 270. Under the intended binary builds, the large pipeline has the
same annual total. The small pipeline costs EUR 120 capital plus EUR 210 expected
operation, giving EUR 330. These are annual-cost hand calculations; they differ
from the earlier upfront-normalized benchmark.

| Case | Intended annual hand optimum EUR | Current checkpoint native verification |
| --- | ---: | --- |
| `continuous_equal` | 270 | Verified: 270 |
| `binary_capacity_cost_equal` | 270 | Deferred to binary checkpoint |
| `binary_fixed_cost_equal` | 270 | Deferred to binary checkpoint |
| `binary_fixed_cost_high_probability` | 288 | Deferred to binary checkpoint |
| `deterministic_binary_control` | 280 | Prior control: 280; ordinary equations unchanged |

New hand tables are generated in `hand_calculations_annual_capex_once/`, leaving
the earlier `hand_calculations/` results available as historical records.

## Reproduction

For a fresh checkout, generate the native inputs once:

```sh
.venv/bin/python -m data.fdm_ccs_binary_test.build_dataset
```

If the case folders already exist, keep the inputs and update only the selected
annual-cost hand calculations:

```sh
.venv/bin/python -m data.fdm_ccs_binary_test.build_dataset --hand-only
```

Run only the continuous financial check at this checkpoint:

```sh
.venv/bin/python -m data.fdm_ccs_binary_test.run_checks --cases continuous_equal
```

Expected exit code is 0. `--cases` can select cases, and `--output PATH` selects
a separate output folder. The default folder is
`checkpoints/stochastic_fixed_investment/fdm_ccs_current/`. Omitting `--cases`
runs the binary cases as well; their retained linkage limitation is a separate
pending step.

The runner uses the ordinary v3 loading, aggregation, construction and solve
path. It adds no test constraints or alternative objectives. Full loaded inputs,
variable CSV/NetCDF solutions, solved LPs, annual operations, capacities,
capital contributions, comparison tables and logs are saved in the selected
output folder. The source code is hashed before and after each run.

The scripts and README are versioned. Generated inputs, full hand tables and
checkpoint results are local and Git-ignored. No large reference dataset is
required or solved.
