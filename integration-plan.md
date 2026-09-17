# Simple workflow for adding stochastic optimization to ZEN-garden v3

Date: 2026-09-17

## Goal

The goal is to reimplement the stochastic scenario-tree model from baeniv’s branch in ZEN-garden v3.

A scenario tree represents several possible futures. The model makes one shared decision before the futures separate, then may make different decisions after each branch becomes known.

The integration branch will use one stochastic execution path. A scenario-tree file is required. A problem with only one possible future is represented by a tree with one path, rather than by a separate deterministic mode.

The additional ZEN-carbon features are not part of this work. They can be considered later if they are needed. The stochastic implementation must not depend on them.

## Code used as the starting point

- ZEN-garden v3 foundation: `main_NB`, matching `upstream/main` at `a1bcb618b268a2bb821e5b3c3518c67567cbe920`.
- Work area: `integration/zen-carbon-v3`. The name is old, but the branch can still be used for the stochastic work.
- Baeniv reference code: `baeniv/main` at `a7f41d68457b8a536541a835114542e8d2f6109c`.
- Test data: `data/MS_Dummy_Model`.

Baeniv’s code was written for an older version of ZEN-garden. Do not combine his whole branch with v3. Read his equations and intended behavior, then implement that behavior using the v3 structure.

## Prepare the work area in GitHub Desktop

Do these steps before writing model code:

1. Click **Fetch origin**. This checks your GitHub repository for new work without changing your files.
2. Select `integration/zen-carbon-v3` as the current branch.
3. Select **Branch → Merge into current branch**, then choose `main_NB`. This brings the current v3 foundation into the integration branch.
4. Confirm that the current branch is still `integration/zen-carbon-v3`.
5. Add and commit this plan and the task summary.
6. Click **Push origin**. This uploads the integration branch to your GitHub repository.

Do not select `baeniv/main` or the johburger branch in the Merge window.

The `MS_Dummy_Model` folder is currently skipped by Git because the repository excludes most files under `data/`. Before the tests can be shared or used automatically, add a specific exception for this testcase or move it into a tracked test-data folder.

## Rules confirmed by the thesis

Use these rules in the v3 implementation:

1. **Probabilities are unconditional:** each number is the total probability of reaching that node. The root probability is `1`. Nodes in the same year must sum to `1`, and a parent’s children must sum to the parent’s probability.
2. **State changes are node-specific:** a multiplier applies only to the node containing it. If a parameter has no state entry at a node, its multiplier is `1`. Repeat a multiplier in later nodes when a change should continue.
3. **Node numbers follow the original input format:** use unique consecutive integers beginning with root node `0`, numbered across generations. Internally, constraints must still follow the explicit parent path rather than calculate history from the node number.
4. **Every path is complete:** every branch reaches the final optimized year and contains the configured investment years in chronological order.
5. **Expected cost uses node probabilities:** multiply every node’s discounted cost by its unconditional probability and then add the results.
6. **History follows ancestors:** cumulative emissions, construction time, lifetime, existing capacity, and diffusion may use only the current node and its ancestors. Sibling branches never share later decisions.
7. **Non-anticipativity is structural:** a decision before branching exists once at the shared ancestor node, so no extra equality constraints are required.
8. **State multipliers are applied last:** first read the base and yearly data, then apply ordinary scenario changes, and finally apply the node-specific multiplier.

Some choices remain open:

1. Define any policy limits not covered by the thesis as per-path, probability-weighted, or final-node rules.
2. Initially reject stochastic runs that also request rolling-horizon optimization or time-series aggregation. The thesis does not confirm these combinations.
3. The exact correction to the incomplete `MS1_5` probability data must be confirmed; do not assume a replacement value.

## Implementation workflow

### Step 1 — prepare reliable tests

1. Make `MS_Dummy_Model` available to the automated tests.
2. Confirm the intended `MS1_5` structure, then correct it: the file contains seven nodes although its description says six. Its final probabilities total 0.75, and the children of node 2 total 0.25 although node 2 has probability 0.5. The thesis confirms that this is invalid but does not give the intended replacement value.
3. Replace machine-specific solver settings, such as 128 Gurobi threads, with small portable test settings.
4. Record the expected objective, investments, operation, emissions, and important constraint values for each accepted case.
5. Create one very small two-stage example that can be calculated by hand. The MS model is useful for regression testing but is too large to prove individual equations clearly.

### Step 2 — create the scenario-tree foundation

Add the scenario-tree service to the v3 core. For every tree node it should store:

- a unique consecutive integer node ID;
- its parent;
- its children;
- its calendar year;
- its stage in the tree;
- its unconditional probability of being reached;
- whether it is a final node;
- any input-value changes at that node.

Validate the tree before building an optimization model. Reject duplicate or non-consecutive node IDs, disconnected nodes, loops, invalid years, incomplete paths, and probabilities that do not satisfy the thesis rules.

The input format uses consecutive integer node IDs beginning with zero. Do not use numerical comparisons such as `previous_id < current_id` to determine model history; follow the stored parent and ancestor relationships instead.

### Step 3 — connect the tree to model inputs and time

1. Keep the calendar year separate from the scenario-tree node.
2. Expand yearly input values to the appropriate nodes.
3. Apply the node-specific multiplier after the base data, yearly data, and ordinary scenario changes. Do not inherit it automatically; repeat it in descendant nodes when it should continue.
4. Make parent, ancestor, child, and final-node relationships available to every model component that needs them.
5. If no scenario tree is supplied, stop with a clear message explaining that this stochastic version requires one. Use a single-path tree for a problem with only one future.

### Step 4 — implement the mathematical behavior

Implement and test the model in this order:

1. Operating variables and operating costs for each node.
2. Investment decisions shared by all futures that have not yet separated. This prevents the model from using future knowledge too early.
3. Construction time, technology lifetime, existing capacity, and capacity additions along each node’s history.
4. Storage, conversion, and transport behavior at each node.
5. Expected total cost using probabilities and correct calendar-year discounting.
6. Cumulative emissions and emissions limits along each path.
7. Technology diffusion using only investments made in the current node or its ancestors. Investments in one future must not help a different future.
8. Fixed-investment runs for calculating the Value of the Stochastic Solution (VSS). This must be a separate option and must not disable investment in the normal stochastic run.

The thesis defines the VSS calculation as three runs:

1. Solve the stochastic tree normally with investments enabled. This gives the recourse-problem cost, `RP`.
2. Solve a single-path tree using probability-weighted average inputs and save its investments.
3. Run the stochastic tree again with those saved investments fixed, while operation remains free. This gives `EEV`.

Calculate `VSS = EEV - RP`. Use this procedure for the tested two-stage case. A correct multi-stage VSS method remains future work.

Use the current v3 equations as the base. Use baeniv’s branch to understand the desired stochastic behavior, not as code to copy directly.

### Step 5 — produce understandable results

For every result, retain:

- the scenario-tree node;
- the parent node;
- the calendar year;
- the probability;
- whether the node is final.

Allow results to be viewed by individual node, by complete path, by calendar year, and as a probability-weighted average. Clearly distinguish weighted results from raw results.

### Step 6 — run the tests in increasing difficulty

Use this order:

1. Invalid-tree tests that do not require a solver, including probability sums, node numbering, complete paths, and configured years.
2. `MS1_0`: use the earlier v3 result only as a numerical reference.
3. `MS1_1`: the single-path tree must reproduce the recorded `MS1_0` reference.
4. `MS1_2`: verify the node-specific natural-gas price change.
5. `MS1_3`: verify branching and shared decisions before the branch.
6. The small hand-calculated two-stage case: verify expected cost and compare it with a model that knows the future in advance.
7. `MS1_4`: verify branching, probabilities, and different prices together.
8. Corrected `MS1_5`: verify construction time and a larger tree.
9. A diffusion case: verify that one branch cannot use investments from another branch.
10. A three-run VSS case: normal stochastic investment, single-path expected-value investment, and fixed-investment stochastic replay.
11. A standard upstream emissions-budget case on a scenario tree.

Only after all of these tests pass should work begin on rolling horizons, time-series aggregation, or large scenario trees.

## Completion requirements

The first stochastic version is complete when:

- a scenario tree is required and a missing tree produces a clear error message;
- a single-path tree reproduces the recorded non-stochastic reference result;
- a valid tree runs without requiring any ZEN-carbon feature;
- invalid trees produce clear error messages;
- decisions made before a branch are shared correctly;
- decisions from one branch never leak into another branch;
- unconditional probability weighting, expected cost, discounting, construction time, lifetime, emissions, and diffusion pass small numerical tests;
- state multipliers apply only at their listed nodes and are not inherited silently;
- the two-stage VSS procedure reproduces `VSS = EEV - RP` without disabling investment in the normal stochastic run;
- results retain clear node, year, path, and probability information;
- the corrected MS test suite passes with recorded expected values;
- the input format and limitations are documented.

## Work postponed until later

Do not include these ZEN-carbon additions in the first stochastic implementation:

- minimum CO2 storage;
- LCA accounting;
- super-node and super-edge limits;
- pooled transport;
- regional or distance-based carbon-model extensions;
- horizon-wide carrier limits.

Standard emissions and carbon-price features already present in upstream ZEN-garden must still work in stochastic mode.

## Short GitHub Desktop glossary

- **Repository:** the project folder and its saved history.
- **Branch:** a separate line of work inside the repository.
- **Commit:** a saved checkpoint containing selected file changes.
- **Fetch:** check GitHub for new commits and branch information without changing the current files.
- **Merge:** bring work from one branch into the current branch.
- **Push:** upload local commits to GitHub.
- **SHA:** the unique identification number for one exact commit.
