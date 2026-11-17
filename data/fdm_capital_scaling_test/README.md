# Small FDM capital-scaling experiment

**Result (17 November 2026):** keeping physical lifetime and discount fixed while
duplicating the operating futures changes the FDM investment decision. Dividing
the CAPEX input by the number of fictitious slots, in separate comparison inputs,
removes that dependence for this annualized-cost experiment.

No production equation, previous dummy dataset, or uploaded dataset was changed.
The large uploaded network was not loaded or solved by this test.

## Your inspection

See the [feature documentation](../../docs/files/zen_garden_in_detail/stochastic_fdm.rst).
After running this experiment, the full comparison is saved locally in
`checkpoints/stochastic_fixed_investment/11_capital_scaling_test/comparison.csv`.
The same physical demand distribution leads to pipeline capacity **40 tonnes/year
with five slots** and **0 with ten slots** when the CAPEX input is unchanged.

## Small physical network

The network copies the earlier two-node continuous CCS control. Free capture
converts raw emissions to captured carbon 1:1 at source. A continuous pipeline and
trucks deliver captured carbon to sink. There are no installation binaries or
demand shortfalls. Pipeline operation costs EUR 1/tonne and trucks EUR 8/tonne.
Each fictitious slot has one aggregated operating timestep representing 8760 hours.

All technologies have lifetime and depreciation time 50, zero construction time,
and zero existing capacity. Discount rate is 5%, matching the uploaded carbon
pipeline's financial settings. All additions occur in the first slot and all
later addition maxima are zero. Capacity therefore survives and is shared across
all slots without retirement or later investment.

The illustrative upfront pipeline quote is **EUR 20 per tonne/year of capacity**.
This is a dummy value chosen to make a changed investment decision visible. It is
not the uploaded network's actual pipeline price. In native units the input is
`20*8760` EUR/(tonne/hour), before any comparison scaling.

## Same uncertainty represented twice

The five-slot case uses probabilities `[9,7,1,9,4]/30`, matching the uploaded
five-future weights, and dummy demands `[40,100,40,100,40]` tonnes/year. Low demand
has total probability 14/30 and high demand 16/30. Expected demand is 72 tonnes.

The ten-slot case duplicates every one of those five futures and gives each copy
half its original probability. Low/high probabilities and expected demand remain
identical. The extra slots add no physical future, information or real elapsed
year to the problem.

## Hand calculation

For pipeline capacity K, demand D and probability p:

```text
operating cost(K,D) = min(K,D) + 8*max(D-K,0)
a = annuity(5%, 50) = 0.05477673549

FDM capital with unchanged inputs = N * a * 20 * K
FDM capital with scaled inputs   = N * a * (20/N) * K = a * 20 * K
```

The scaled-input comparison targets **one annualized capital payment plus expected
annual operation**. This differs from the earlier dummy test's explicitly chosen
upfront-cost-once target. It is not a claim that the author intended this target,
or that these scaled inputs were used in the uploaded dataset.

| Case | Pipeline capacity t/year | Capital EUR | Expected operation EUR | Total EUR |
| --- | ---: | ---: | ---: | ---: |
| Five slots, unchanged CAPEX | 40 | 219.106942 | 296 | 515.106942 |
| Ten slots, unchanged CAPEX | 0 | 0 | 576 | 576 |
| Five slots, CAPEX divided by 5 | 100 | 109.553471 | 72 | 181.553471 |
| Ten slots, CAPEX divided by 10 | 100 | 109.553471 | 72 | 181.553471 |

Independent sweeps of capacities 0–100 are saved in `hand_calculations/*.csv`.
All four native solves match those hand calculations, meet all demand, share
capacity across futures, and make no later additions or investments.

## Reproduction

Generate the base CCS inputs first if they do not already exist:

```sh
.venv/bin/python -m data.fdm_ccs_binary_test.build_dataset
```

From the repository root, run the experiment:

```sh
.venv/bin/python -m data.fdm_capital_scaling_test.check_scaling
```

Expected exit code is 0. The script uses existing saved case inputs if present;
otherwise it copies the earlier continuous CCS control and creates the new cases.
It calls the ordinary v3 construction and solve methods without adding test
constraints or changing the objective. Generated inputs are under `cases/`.

The local directory `checkpoints/stochastic_fixed_investment/11_capital_scaling_test/`
contains full solver logs, loaded parameter tables, solved LP files, per-variable
CSV/NetCDF solutions, equation terms, annual flows, hand comparisons, and source
hashes proving production code was unchanged. This script and README are
versioned; generated inputs, hand tables and outputs remain local and Git-ignored.
