# More reviewers per round (a council of same-prompt reviewers)

## Why this is out of scope

Measured against real ground truth (#108, follow-up of 2026-10-09):

- One reviewer caught 5.8 of 8 known defects on average.
- Councils of 3 or 5 caught 6.0, whether combined by union or by majority.
- The two defects nobody caught were missed by Claude and Codex reviewers alike.
- In the real PR, those defects surfaced only in a later round, after fixes.

Adding reviewers adds cost, not recall. The budget goes into rounds: one
independent cross-provider reviewer per round, then fix, then review again.

## What would reopen it

Evidence that a *differently prompted* second reviewer (for example, one that
enumerates input shapes the code doesn't validate) catches defects the
single-reviewer loop misses.

## Prior requests

- #9 (adversarial subagent per round), #104, #108
