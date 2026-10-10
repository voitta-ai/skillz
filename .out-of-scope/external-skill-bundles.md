# Subscribing to an external skill bundle as a marketplace source

## Why this is out of scope

- An external bundle installs as a whole, and every model-invoked skill in it adds
  to the always-on description listing. A full always-on config was measured
  quality-neutral at 1.6-1.7x the cost (hq#167, E1).
- Bundles bring skills that contradict measured findings here (see
  `agent-written-tests.md`).
- Auto-updated skill text is auto-updated instructions to the agent, from an
  author we don't review. That is a supply-chain risk.

Instead, ideas from MIT-licensed external skills are copied into our own skills,
with credit, when they address an observed failure (see SCOPE.md).

## What would reopen it

A bundle that installs per skill, whose skills don't conflict with our measured
process, and whose updates we can pin and review.

## Prior requests

- mattpocock/skills (evaluated 2026-10-09; five ideas mined into our skills instead)
