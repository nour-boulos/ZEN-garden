# Stochastic integration task summary

This is the short working checklist. Follow the tasks from top to bottom. Detailed explanations are in `integration-plan.md`.

Status meanings:

- **Not started:** no implementation work has begun.
- **In progress:** someone is actively working on it.
- **Blocked:** a decision or missing input prevents progress.
- **Done:** the completion check has passed.

## A. Prepare the work area

| ID | Task | Complete when | Status |
|---|---|---|---|
| A1 | Fetch `origin` in GitHub Desktop | GitHub Desktop reports the remote information is current | Done |
| A2 | Bring `main_NB` into `integration/zen-carbon-v3` | The integration branch contains foundation commit `a1bcb618…` | Not started |
| A3 | Commit the plan and task summary | Both Markdown files appear in the integration branch history | Not started |
| A4 | Push the integration branch | GitHub shows the same latest commit on `origin/integration/zen-carbon-v3` | Not started |
| A5 | Make the MS testcase trackable | The testcase is included in the repository and available to automated tests | Not started |

## B. Prepare the tests

| ID | Task | Complete when | Status |
|---|---|---|---|
| B1 | Confirm and correct the `MS1_5` node count | Its description and actual structure agree | Not started |
| B2 | Confirm and correct the `MS1_5` probabilities | Probability mass is complete and passes validation | Not started |
| B3 | Make solver settings portable | Test settings do not require 128 Gurobi threads or one specific machine | Not started |
| B4 | Record the earlier v3 `MS1_0` reference results | Objective, investments, operation, emissions, and solver versions are saved for comparison | Not started |
| B5 | Define expected results for `MS1_1`–`MS1_5` | Each case has numerical values and tolerances to check | Not started |
| B6 | Create a tiny hand-calculated tree | Expected decisions and objective can be verified without trusting the software | Not started |

## C. Define the input rules

| ID | Task | Complete when | Status |
|---|---|---|---|
| C1 | Record the thesis probability rule | Inputs use unconditional probabilities; root, generation, and parent-child sums are documented | Done |
| C2 | Record the thesis state rule | State multipliers are node-specific, default to 1, and are repeated when they should continue | Done |
| C3 | Complete policy-limit rules | Thesis-defined emissions behavior is retained and any additional policies are classified as per-path, weighted, or final-node | In progress |
| C4 | Define the scenario-tree file format | Required fields, optional fields, and examples are documented | Not started |
| C5 | Define initial limitations | Rolling horizon and time-series aggregation are rejected clearly when combined with a tree | Not started |

## D. Build the scenario-tree foundation

| ID | Task | Complete when | Status |
|---|---|---|---|
| D1 | Add the required tree service | The stochastic v3 model reads a tree and clearly rejects a missing tree | Not started |
| D2 | Validate tree structure | Duplicate or non-consecutive IDs, loops, disconnected nodes, incomplete paths, bad years, and bad probabilities are rejected | Not started |
| D3 | Implement thesis node numbering safely | Inputs use consecutive integers from zero, while model history follows parent links rather than numerical comparisons | Not started |
| D4 | Store parent, child, ancestor, stage, year, probability, and final-node information | All required model components can access these relationships | Not started |
| D5 | Apply node-specific input changes | Multipliers are applied last, default to 1, and affect only the listed nodes | Not started |

## E. Add stochastic mathematics

| ID | Task | Complete when | Status |
|---|---|---|---|
| E1 | Add node-specific operation and costs | Operating decisions and costs are available for every node | Not started |
| E2 | Share decisions before branching | Tests show that the model cannot use future knowledge early | Not started |
| E3 | Add construction and lifetime history | Capacity follows the correct ancestor path and elapsed years | Not started |
| E4 | Add storage, conversion, and transport behavior | Each component passes a small tree test | Not started |
| E5 | Add probability-weighted discounted cost | The hand-calculated objective matches the model | Not started |
| E6 | Add cumulative emissions behavior | Emissions follow the correct path and policy rule | Not started |
| E7 | Add ancestor-only diffusion | A sibling branch cannot affect another sibling’s diffusion limit | Not started |
| E8 | Add the three-run VSS workflow | RP, single-path expected value, and fixed-investment replay produce `VSS = EEV - RP` without disabling normal stochastic investment | Not started |

## F. Add results and diagnostics

| ID | Task | Complete when | Status |
|---|---|---|---|
| F1 | Save node metadata with results | Node, parent, year, probability, and final-node status are preserved | Not started |
| F2 | Add node and path result views | Users can inspect one node or one complete future path | Not started |
| F3 | Add expected-value result views | Weighted and unweighted results are labelled separately | Not started |
| F4 | Add clear error messages | Bad trees, missing values, and invalid fixed investments explain the problem | Not started |

## G. Acceptance tests

| ID | Test | Pass condition | Status |
|---|---|---|---|
| G1 | Invalid tree inputs | Bad probability sums, numbering, paths, topology, and years are rejected with the expected message | Not started |
| G2 | Recorded `MS1_0` reference | The reference outputs and software versions are complete | Not started |
| G3 | `MS1_1` single-path equivalence | The stochastic single-path result matches the recorded `MS1_0` reference within tolerance | Not started |
| G4 | `MS1_2` value change | The gas-price change produces the expected cost and operation | Not started |
| G5 | `MS1_3` branching | Pre-branch decisions are shared and expected values are correct | Not started |
| G6 | Hand-calculated tree | Decisions and objective match the manual calculation | Not started |
| G7 | `MS1_4` branching plus value changes | Probabilities, shared decisions, and leaf operation are correct | Not started |
| G8 | Corrected `MS1_5` | Construction time and the larger tree behave correctly | Not started |
| G9 | Diffusion isolation | One branch cannot use investments made in another branch | Not started |
| G10 | Two-stage VSS workflow | The three runs reproduce fixed decisions and calculate `VSS = EEV - RP` | Not started |
| G11 | Upstream emissions budget | Standard emissions behavior works on the tree | Not started |

## H. Documentation and release readiness

| ID | Task | Complete when | Status |
|---|---|---|---|
| H1 | Document the stochastic workflow | A new user can create a tree and run the stochastic v3 model | Not started |
| H2 | Document the tree format | Valid examples and validation errors are shown | Not started |
| H3 | Document known limitations | Unsupported combinations are listed clearly | Not started |
| H4 | Run the complete relevant test suite | The v3 component tests and all new stochastic tests pass | Not started |
| H5 | Review against completion requirements | Every requirement in `integration-plan.md` is satisfied | Not started |

## Work explicitly postponed

- ZEN-carbon minimum CO2 storage
- LCA accounting
- super-node and super-edge limits
- pooled transport
- other ZEN-carbon fork extensions
- stochastic rolling-horizon support
- stochastic time-series aggregation
- performance testing on large scenario trees
