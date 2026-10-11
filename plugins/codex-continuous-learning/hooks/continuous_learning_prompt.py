#!/usr/bin/env python3
"""UserPromptSubmit hook for the codex-continuous-learning bundle.

Emits a single-line reminder that the agent should keep an eye out for
reusable, verified learnings during the task and run the
continuous-learning retrospective before exit.

Contract:
- stdout: text appended to the user's prompt context (one short line).
- exit code 0: hook succeeded.
- non-zero exit code: hook failed, but `on_error: ignore` in hooks.json
  ensures the session continues.

This script is intentionally dependency-free: no third-party imports,
no filesystem writes, no network. If the bundle is installed but the
skill itself is missing, the reminder is still useful prose.
"""

import sys


REMINDER = (
    "[continuous-learning] If this turn produces a reusable, verified "
    "learning, plan to capture it as a skill update or new skill before "
    "the Stop hook fires. Otherwise plan to emit `No reusable learning.`"
)


def main() -> int:
    print(REMINDER)
    return 0


if __name__ == "__main__":
    sys.exit(main())
