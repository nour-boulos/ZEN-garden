Fixed-investment FDM stochastic mode
====================================

Set ``system.use_stochastic_fdm: true`` to optimize one shared investment and
operate it in alternative futures represented by fictitious model years. The
flag defaults to false. Ordinary deterministic and scenario-tree modes retain
their existing accounting when the flag is false.

The implementation is based on ``fradmm/ZEN-garden`` commit ``d93afc48``. The
literal v3 port is preserved at commit ``88447656``. The current version makes
one deliberate financial correction: the shared annual capital charge enters
the objective once, in the first fictitious slot. The original reliability
factor and pipeline binary constraints remain unchanged.

Fictitious slots and shared capacity
------------------------------------

Each slot represents an alternative operating future for one physical year.
For two futures, use::

    use_stochastic_fdm: true
    use_scenariotree: false
    use_rolling_horizon: false
    optimized_years: 2
    interval_between_years: 1
    allow_investment: true

Provide ordinary year-specific operating files or yearly-variation files for
the futures. The scenario-analysis tool may select or scale inputs, but its
separate outer runs do not couple investment decisions between models.

``capacity_addition_max`` accepts a year index. Permit additions in the first
slot and set their maximum to zero in later slots. With zero construction time
and capacity surviving every slot, the native capacity-history equations retain
that initial investment. It is optimized by the model, not supplied as an answer.
A technology input file may contain::

    year,capacity_addition_max
    2026,inf
    2027,0

A finite capacity limit can bound a continuous investment. The legacy direct
FDM addition bound, including its binary limitation described below, is retained.

Annual cost accounting
----------------------

This mode compares costs for one representative operating year of a long-lived
network. Keep the intended financial discount rate and depreciation time. V3
uses depreciation time for the annuity and defaults it to technology lifetime
when no separate value is supplied. The fictitious-slot capacity history still
requires assets to remain available across all operating futures.

Define ``probability`` and ``expected_loss_of_load`` in the energy-system
attributes with dimensionless unit ``1``. Probabilities can be provided in
``energy_system/probability.csv`` with ``year,probability`` columns and should
sum to one. Do not combine FDM with scenario-tree probability weighting.

The corrected equations are::

    capital_weight[first_slot] = 1
    capital_weight[other_slots] = 0

    total_cost[s] = capital_weight[s] * annual_capital[s]
                  + probability[s] * (technology_operation[s]
                                    + carrier_cost[s] + carbon_cost[s])
    net_present_cost[s] = total_cost[s]
    objective = sum_s net_present_cost[s]
              = annual_capital[first_slot] + expected_running_cost

``CostTotalConstraint`` selects the first model slot from the model schema; its
coordinate need not be zero. The common capital charge does not depend on that
future's probability. The mask applies to the aggregate annual charge for all
capital assets, including conversion, transport, storage and existing-capital
costs already included in that aggregate.

Only the contribution to total cost changes. ``cost_capex_yearly`` and
``cost_capex_yearly_total`` remain calculated normally in every slot. For a
shared surviving investment their values are identical, but only the first
contributes capital to ``cost_total``. The reported net-present-cost contributions
still sum to the objective. Summing the descriptive annual-capital values over
alternative futures is not the capital contribution to that objective.

There is no discounting between fictitious futures. The financial discount rate
still determines the annual-equivalent capital charge. For example, an EUR 800
investment at 5% over 50 years has annual cost EUR 43.821388. With five futures,
the current objective includes that amount once. The original port included
five such charges, EUR 219.106942, despite zero new investment after slot zero.

No input CAPEX division by the number of futures is needed. The older
zero-discount, depreciation-equal-to-slot-count hand example compensated for
legacy repetition to recover upfront capital once. It is a different cost basis,
not the current annual-cost convention. Reusing such compensation would change
the economic input and should not be combined with this correction.

A simple check starts with EUR 100 upfront, two-year depreciation and a 5% rate.
Its annual capital charge is EUR 53.780488. Two equally likely operating futures
costing EUR 10 and EUR 30 have expected operation EUR 20. The objective is now
EUR 73.780488, rather than the original port's EUR 127.560976.

Reliability equation
--------------------

The original FDM reliability equation and factor 0.5 are retained::

    sum_(carrier,s) [probability[s] * 0.5
                     * annual_shed_demand[carrier,s]
                     / annual_demand[carrier,s]] <= expected_loss_of_load

Only positive-demand carrier/slot pairs contribute. The CCS benchmarks prohibit
shedding with an infinite shedding price and a zero reliability threshold. The
factor has no effect when all demand is met.

Binary installation limitation remains
--------------------------------------

The financial correction does not change FDM's direct maximum-addition bound::

    capacity_addition[technology,location,s] <= maximum_addition[technology,s]

It does not multiply this upper bound by the installation binary. The existing
minimum-addition constraint alone does not force the binary to one for positive
capacity. The retained unit check still demonstrates positive capacity with a
zero binary. This checkpoint does not repair that behavior.

At preserved port commit ``88447656``, native CCS cases demonstrated partial
catalogue sizes and avoided fixed build charges. Those historical objective
values used the legacy capital accounting and are not the new annual-cost
benchmarks. The native binary cases have not yet been retested after the
financial correction; they are the next separate implementation step.

The existing binary-creation rules are unchanged. A continuous example uses an
infinite first-slot maximum, zero later maxima, zero minimum additions and no
fixed distance-dependent build cost. A finite total capacity limit can still
bound that continuous capacity.

Reproducing the small tests
---------------------------

The source includes generators and runners under ``data/fdm_ccs_binary_test``
and ``data/fdm_capital_scaling_test``. Generated native inputs, hand tables and
full solver logs remain local and Git-ignored. No large reference dataset is
required.

Generate the base native inputs once from a source checkout::

    python -m data.fdm_ccs_binary_test.build_dataset

If those case folders already exist, regenerate only the annual-cost hand
calculations without changing the saved native inputs::

    python -m data.fdm_ccs_binary_test.build_dataset --hand-only

Run the unit suite and current continuous-only benchmarks::

    python -m pytest -n 0 tests/unit_tests
    python -m data.fdm_ccs_binary_test.run_checks --cases continuous_equal
    python -m data.fdm_capital_scaling_test.check_scaling

These commands exit with status zero for the capital-accounting checkpoint.
The CCS runner also supports ``--output PATH`` for a separate output directory.
Omitting ``--cases`` includes the existing binary cases, whose correction and
native retest are deferred to the next step.

.. list-table:: Verified current annual-cost checks
   :header-rows: 1

   * - Case
     - Pipeline capacity (tonnes/year)
     - Annual capital in objective (EUR)
     - Expected operation (EUR)
     - Objective (EUR)
   * - Two-slot continuous CCS, zero discount, two-year depreciation
     - 100
     - 200
     - 70
     - 270
   * - Five futures, 5% and 50 years, unscaled CAPEX
     - 100
     - 109.553471
     - 72
     - 181.553471
   * - Ten duplicated futures with halved probabilities
     - 100
     - 109.553471
     - 72
     - 181.553471
   * - Five futures with demand/probability pairs listed in a different order
     - 100
     - 109.553471
     - 72
     - 181.553471

All native cases have free 1:1 capture, pipelines and trucks, no demand shedding,
shared capacity and no later investment. Listing futures in a different order
moves demand and its probability together; it does not change the uncertainty.
The five- and ten-slot cases keep the same financial lifetime and upfront quote,
without dividing it by the number of futures.

The unit suite has 35 passing cases, including ordinary-cost controls and tests
for a single future, a nonzero first coordinate, a zero-probability first future,
retained annual-capital variables and all three running-cost components.

The CCS runner writes its default outputs to
``checkpoints/stochastic_fixed_investment/fdm_ccs_current``. The capital runner
writes to ``18_capex_correction/capital_cases`` under the same checkpoint root.
Each provides comparison CSVs, JSON summaries, solved LP files, full per-variable
CSV/NetCDF solutions, annual operations and the capital objective contribution.
The runners preserve earlier generated inputs and historical output folders.

Implementation scope
--------------------

The only production equation changed for this correction is in
``CostTotalConstraint.build``. The annualization, objective-summation,
inter-future discounting, investment bounds, capacity history, reliability and
binary equations remain unchanged. Ordinary modes retain their original capital
contributions in every actual planning year.

Both the original implementation and v3 solve with ``sanitize_zeros=True``.
This existing Linopy cleanup removes inactive placeholder terms before solve;
no new coefficient cleanup is introduced here. These tests use that ordinary
solve lifecycle and export the solved models successfully.
