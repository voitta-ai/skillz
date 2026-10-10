# Scope

This catalog holds repeatable procedures that agents load on demand. Every skill
costs every session a description in the always-on listing, and a full always-on
config was measured as quality-neutral at 1.6-1.7x the cost. So a skill has to
earn its place.

## The bar

A new skill, or a change to one, has to clear all three:

1. **Observed failure or measured result.** It comes from something that went
   wrong in a real session (what ran, what happened, what was expected) or from a
   measurement. "It would be better if..." doesn't clear this.
2. **A procedure, not a specific.** A repeatable procedure with judgement belongs
   here. A one-off cause and fix, an API gotcha or a project quirk belongs in
   memory (voitta-ai/skillz-memory or a private memory file).
3. **Consistent with what we measured.** It doesn't contradict a finding recorded
   in [`.out-of-scope/`](./.out-of-scope/), unless it brings new evidence that
   overturns it.

## Already decided

Each file in [`.out-of-scope/`](./.out-of-scope/) records one rejected idea, the
evidence behind the rejection, and what would reopen it. Read them before
proposing:

- [`agent-written-tests.md`](./.out-of-scope/agent-written-tests.md)
- [`same-provider-review-council.md`](./.out-of-scope/same-provider-review-council.md)
- [`external-skill-bundles.md`](./.out-of-scope/external-skill-bundles.md)
