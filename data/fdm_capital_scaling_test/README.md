# Shared annual CAPEX: duplication and order checks

The corrected FDM objective includes the initial investment's annual capital
charge once. Five futures, ten duplicated futures, and five futures listed in a
different order all choose **100 tonnes/year** of pipeline capacity and return
**EUR 181.553471**. The 5% discount rate, 50-year depreciation and upfront quote
are unchanged between cases. No CAPEX input is divided by the number of futures.

The literal FDM port before this correction is preserved in commit `88447656`.
See the [feature guide](../../docs/files/zen_garden_in_detail/stochastic_fdm.rst)
for the current equation and the separate remaining binary limitation.

## Small physical network

There are two nodes and one corridor. Free capture converts raw emissions to
captured carbon 1:1 at source. A continuous pipeline and trucks deliver it to
sink. Pipeline operation costs EUR 1/tonne and trucks EUR 8/tonne. Captured-carbon
imports and demand shedding are prohibited. There are no installation binaries.
One aggregated operating timestep represents 8760 hours in each future.

All technologies have lifetime and depreciation 50, zero construction time and
no existing capacity. The initial investment is optimized and later additions
are prohibited. Capacity survives all slots. The upfront pipeline quote is
EUR 20 per tonne/year of capacity, entered as `20*8760` EUR/(tonne/hour).

## Same physical uncertainty

The five-future case has probabilities `[9,7,1,9,4]/30` and demand
`[40,100,40,100,40]` tonnes/year. Low demand has probability 14/30, high demand
16/30 and expected demand 72 tonnes/year.

The ten-future case duplicates every demand/probability pair and halves each
copy's probability. The reordered case rotates those pairs together, so high
rather than low demand appears first. Neither change adds a real year or changes
the physical demand distribution. Only the accounting slot containing common
capital differs; the investment decision and objective should stay the same.

## Independent hand calculation

The annual capital factor at 5% and 50 years is 0.05477673549. For pipeline
capacity K, the selected annual cost basis is:

```text
annual capital = 0.05477673549 * 20 * K
operation(K,D) = min(K,D) + 8*max(D-K,0)
objective = annual capital + sum(probability * operation)
```

The hand minimum is K=100. Annual capital is EUR 109.553471 and expected operation
is EUR 72, totaling EUR 181.553471. Independent sweeps of K=0..100 are generated
under `hand_calculations_annual_capex_once/`.

The underlying annual capital variable remains EUR 109.553471 in every future.
Its objective contribution is EUR 109.553471 in the first slot and zero in all
others. Each case checks both facts and verifies that the net-present-cost
contributions sum to the objective. It also checks no later investment, shared
capacity and zero shedding.

## Reproduction and outputs

Create the base CCS inputs first if they do not exist:

```sh
.venv/bin/python -m data.fdm_ccs_binary_test.build_dataset
```

Then run:

```sh
.venv/bin/python -m data.fdm_capital_scaling_test.check_scaling
```

Expected exit code is 0. The new native inputs are written under
`cases_annual_capex_once/`, leaving the earlier `cases/` files unchanged.
Full outputs go to
`checkpoints/stochastic_fixed_investment/18_capex_correction/capital_cases/`.

The output includes a comparison CSV, JSON summaries, full solver logs, solved
LPs, per-variable CSV/NetCDF solutions, loaded input tables, annual operations
and `capital_objective_contribution.csv`. Production-source hashes are checked
before and after the run. This script changes no model equation while running.
Generated inputs, hand calculations and results remain local and Git-ignored.
