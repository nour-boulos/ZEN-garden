Fixed-investment FDM stochastic mode
====================================

Set ``system.use_stochastic_fdm: true`` to use the stochastic equations from
``fradmm/ZEN-garden`` commit ``d93afc48`` through the v3 component interfaces.
The flag defaults to false. The existing deterministic and scenario-tree modes
keep their existing cost equations when the flag is false.

This is a port of the FDM formulation. It does not introduce another scenario
dimension, a different investment objective, new reliability normalization, or
additional installation-binary constraints.

This checkpoint deliberately preserves the legacy behavior before corrections.
The small native benchmarks reproduce two known limitations: repeated annual
capital charges and pipeline capacity that is not linked to its build binary.
Both are described below. Passing port tests establishes legacy parity, not that
these limitations have been repaired.

Fictitious slots and shared capacity
------------------------------------

Each model year is a fictitious operating-future slot for one physical year.
For two futures, the relevant system settings are::

    use_stochastic_fdm: true
    use_scenariotree: false
    use_rolling_horizon: false
    optimized_years: 2
    interval_between_years: 1
    allow_investment: true

Use ordinary year-specific demand files or yearly-variation files for the two
futures. The scenario-analysis tool may select or scale these input files;
separate outer scenario-analysis jobs are separate optimization problems.

``capacity_addition_max`` now accepts a year index. Permit initial additions
in the first fictitious slot and set their maximum to zero in every later
slot. With zero construction time and a lifetime covering all slots, the
ordinary capacity-history equations retain the initial capacity in each future.
No fixed investment values are supplied: the initial investment is optimized.

For example, a technology input file ``capacity_addition_max.csv`` may contain::

    year,capacity_addition_max
    2026,inf
    2027,0

Units are taken from the technology's attribute definition. A finite capacity
limit can bound the initial continuous investment. In ordinary mode, the
previous interpretation of a zero maximum-addition value is retained.

Probabilities, costs and annuity
--------------------------------

Define ``probability`` and ``expected_loss_of_load`` in the energy-system
attributes with dimensionless unit ``1``. Probabilities can also be provided
in ``energy_system/probability.csv`` with ``year,probability`` columns. They
should describe the probabilities of the operating futures.

The port retains these FDM equations::

    total_cost[s] = annual_capital[s]
                  + probability[s] * (technology_operation[s]
                                    + carrier_cost[s] + carbon_cost[s])
    net_present_cost[s] = total_cost[s]
    objective = sum_s net_present_cost[s]

There is no discounting between fictitious slots. The existing v3 capital
annualization is retained. At zero discount, depreciation time N gives annuity
1/N. With N slots, an initial investment's N annual capital terms sum to its
upfront cost. This is the input normalization used by the original hand-test
benchmark; it is not a required financial convention for FDM. In v3, depreciation
time defaults to lifetime. If explicitly provided, it must be set consistently
with the intended cost basis.

These are input conventions, not settings automatically changed by this port.
Do not combine this mode with scenario-tree probability weighting. A nonzero
discount rate or a different economic capital-cost target requires the original
FDM input normalization to be understood before interpreting the objective.

Known annual-capital counting limitation
----------------------------------------

Prohibiting later capacity additions eliminates later new investment. It does
not eliminate the annualized charge associated with the first investment.
``CostCapexYearlyConstraint`` retains prior overnight costs inside the depreciation
window. ``CostTotalConstraint`` includes the full annual capital term in every
slot, and ``TotalCost`` sums those terms without another probability average.

For an initial overnight cost C that survives N fictitious slots and an annuity
factor a, the retained objective therefore contains::

    N * a * C + sum_s probability[s] * running_cost[s]

For example, at 5% and a financial lifetime of 50 years, an EUR 800 investment
has an annual charge of EUR 43.821388. With five operating futures, later new
overnight costs are zero, but five annual charges total EUR 219.106942.
The 5% rate still determines the annuity; discounting between alternative
futures remains disabled.

For a single representative operating year's annual-cost objective, the intended
capital contribution is one annual charge, a*C. For an upfront-cost objective it
is C. These are different accounting targets. Neither follows automatically from
holding investment fixed across futures.

A small continuous CCS experiment keeps a 5% rate, 50-year depreciation and the
same physical demand distribution. Duplicating each future and halving its
probability changes the chosen pipeline capacity from 40 tonnes/year with five
slots to zero with ten slots when CAPEX inputs are unchanged. Separate diagnostic
inputs dividing CAPEX by N recover one annual charge and give identical results
for both representations. That scaling is not automatically applied by this port.

The planned next change is to include the shared annual capital charge once,
while keeping the chosen financial rate and real financial lifetimes. That
would intentionally depart from the literal FDM objective and is not included
in this checkpoint. Pipeline binary behavior is a separate subsequent step.

Reliability equation
--------------------

The original FDM constraint is retained, including its factor 0.5::

    sum_(carrier,s) [probability[s] * 0.5
                     * annual_shed_demand[carrier,s]
                     / annual_demand[carrier,s]] <= expected_loss_of_load

Only positive-demand carrier/slot pairs contribute. The factor is not replaced
by another reliability metric. For the CO2 dummy test, demand shedding remains
prohibited and the threshold can be zero.

Binary installation behavior
----------------------------

FDM's maximum-addition constraint is a direct bound, including zero::

    capacity_addition[technology,location,s] <= maximum_addition[technology,s]

It does not multiply this upper bound by an installation binary. This behavior
is deliberately retained. The existing minimum-addition constraint alone does
not force an installation binary to one whenever positive capacity is added.
The native CCS benchmark confirms the limitation. With catalogue sizes of 60
and 100 tonnes/year, a per-capacity-cost case installs only 40 tonnes/year in
the large pipeline while leaving its build binary at zero. With fixed build
costs, the model can use pipeline capacity without paying those build costs.
This behavior is reported and retained in this commit.

The existing v3 binary-variable creation rules are retained. A finite positive
maximum can therefore create a binary even when the FDM direct bound does not
use it. A continuous example can use an infinite first-slot addition maximum,
zero later maxima, zero minimum additions and no fixed distance-based build cost.

Implementation and checks
-------------------------

The energy-system inputs are ``GenericParameter`` classes; total cost, discount
treatment and reliability use ``GenericConstraint`` classes. The year dimension
of maximum additions is reflected in installation masks and capacity-bound
lookups. No scenario-tree, diffusion or yearly-operation-cost equations are
changed by this port.

Both the original implementation and current v3 solve with
``sanitize_zeros=True``. This existing Linopy cleanup also drops terms whose
coefficient is NaN. A raw pre-solve LP export can therefore reject placeholders
that the normal solve path removes. Checks of the solved/exported model should
use the actual solve lifecycle; no new coefficient cleanup is introduced here.

Reproducing the small benchmarks
--------------------------------

The committed generators and runners are under ``data/fdm_ccs_binary_test`` and
``data/fdm_capital_scaling_test``. Their generated native inputs, full hand tables,
solver outputs and logs remain local and Git-ignored. The large reference dataset
is not required and is not included.

From a source checkout with dependencies and HiGHS installed, generate the small
native cases once::

    python -m data.fdm_ccs_binary_test.build_dataset

The generator refuses to overwrite existing case folders. If they already exist,
use the saved inputs and proceed directly to the checks::

    python -m pytest -n 0 tests/unit_tests
    python -m data.fdm_ccs_binary_test.run_checks
    python -m data.fdm_capital_scaling_test.check_scaling

The CCS runner is expected to exit with status 1 at this checkpoint: all five
models solve to optimality, but the intended binary build and hand-optimum checks
fail. The capital-scaling runner exits with status 0 because all four solves match
the retained FDM equations and their independent hand calculations; the unscaled
results demonstrate the accounting limitation rather than correct it.

.. list-table:: Native CCS benchmark at this checkpoint
   :header-rows: 1

   * - Case
     - Hand cost (EUR)
     - Native cost (EUR)
     - Interpretation
   * - Continuous, normalized upfront-capital test
     - 440
     - 440
     - Pass
   * - Binary sizes, capacity-priced investment
     - 450
     - 440
     - Partial catalogue size is allowed
   * - Binary sizes, fixed build cost
     - 450
     - 70
     - Positive capacity with zero build binary
   * - Binary fixed build, high-demand probability 0.8
     - 488
     - 88
     - Fixed investment charge is avoided
   * - Ordinary deterministic binary control
     - 280
     - 280
     - Pass

All cases have free 1:1 capture, pipelines and trucks, and zero unmet demand.
The binary hand calculation includes building neither, either, or both pipeline
technologies, so it does not assume an exclusivity rule absent from the model.

``checkpoints/stochastic_fixed_investment/09_ccs_binary_test`` receives the full
CCS results, and ``11_capital_scaling_test`` receives the capital-counting results.
Each contains a comparison CSV, JSON summary, solved LP models, per-variable
CSV/NetCDF solutions and full solver logs. The benchmark READMEs describe the
input units and independent hand calculations. The unit suite contains ten FDM
checks and passed with 31 tests overall when this port was validated.
