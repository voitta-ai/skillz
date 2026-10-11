#!/usr/bin/env python3
"""Stop hook for the codex-continuous-learning bundle.

Forces a brief retrospective at end-of-task: the agent must either
invoke the `continuous-learning` skill (and act on its output) or
emit the literal line `No reusable learning.` and exit.

Contract:
- stdout: instruction text appended to the model context for its final
  turn before exit.
- exit code 0: hook succeeded.
- non-zero exit code: hook failed, but `on_error: ignore` in hooks.json
  ensures the session still terminates cleanly.

The hook deliberately does NOT block exit. Blocking would convert a
noisy retrospective into a session-killer; the SKILL.md commits to a
soft-failure design (see SKILL.md > Notes > "Stop hook vs prompt
hook"). The point of the stop hook is the prompt, not enforcement.
"""

import sys


INSTRUCTION = (
    "[continuous-learning] End-of-task retrospective required. Run the "
    "`continuous-learning` skill's four retrospective questions "
    "(discovery cost, recurrence likelihood, verifiable trigger, "
    "verified result). If any answer is no/unclear, emit exactly:\n"
    "\n"
    "    No reusable learning.\n"
    "\n"
    "Otherwise update an existing skill or create a new one per the "
    "skill's `Solution` section. Print the resulting path or diff."
)


def main() -> int:
    print(INSTRUCTION)
    return 0


if __name__ == "__main__":
    sys.exit(main())
