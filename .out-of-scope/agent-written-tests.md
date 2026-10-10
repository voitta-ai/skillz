# A skill that has the agent write its own tests first (TDD by default)

## Why this is out of scope

A measured comparison replayed two real changes with and without the instruction
"before implementing, write an executable check for the exit criteria, run it,
and keep going until it passes" (hq#168, E2). The checks the agent wrote only
confirmed its own reading of the task. They let through as many hidden defects as
the no-tests variant, and cost 20-48% more. What found defects was an
*independent* reviewer from a different model provider: 3-6 high-severity
findings in every diff.

So the default stays: no agent-written tests unless asked. Independent review
(`codex-adversarial-pr-review`, `review-pr-loop`) is where verification effort
goes.

## What would reopen it

A variant E2 didn't test: test seams agreed with a human beforehand, and expected
values taken from an independent source (the spec, a worked example), never from
the implementation. It reopens if a run measured the way E2 was shows that variant
catching defects the independent reviewer misses, at acceptable cost.

## Prior requests

- mattpocock/skills `tdd` (evaluated 2026-10-09; not adopted)
