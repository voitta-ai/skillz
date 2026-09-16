#!/usr/bin/env python3
"""PreToolUse hook: catch credentials embedded in a Bash command before it runs.

What this actually prevents, stated precisely because an earlier version
overclaimed and an overclaim here is dangerous:

  CLOSED by denying at PreToolUse -- `argv` (readable by anything that can run
  `ps` while the process lives), the permission allowlist entry, spilled
  tool-output files, and executed-command logs such as shell history.

  NOT CLOSED -- the transcript. The assistant's tool_use block carrying the
  command string is persisted whether or not the call is allowed, so a denial
  does NOT mean the secret was contained. If a real credential reached a
  command, ROTATE IT. Believing otherwise is the most expensive mistake in
  this domain.

Detection is deliberately the easy half: prose defeats redaction, but a command
line is short and structured, so matching known credential shapes is accurate.

Advisory by default -- it asks rather than blocks, because a control that
false-positives on real work gets disabled and then protects nothing.

    SECRETS_HOOK_MODE=ask    (default) surface it, let the operator decide
    SECRETS_HOOK_MODE=deny   refuse the command outright
    SECRETS_HOOK_MODE=off    disable

Stdlib only, by design: this runs on every Bash call.

NOTE TO ANYONE EDITING THIS FILE: never put a matched value into the response,
into stderr, or into any log. A secret-detector that emits secrets is the same
bug one layer down. Report the shape and the offset only.
"""

import json
import os
import re
import sys

MAX_FINDINGS = 12          # keep the report readable and bounded
REDACT_HINT = "credential-shaped string"

# `_` is a word character, so `\btoken\b` never matches inside GITHUB_TOKEN.
# These lookarounds treat `_` as a boundary, which is what we actually want.
_L = r"(?<![A-Za-z0-9])"
_R = r"(?![A-Za-z0-9])"

# Structured, high-confidence credential prefixes.
#
# Bodies are intentionally NOT allowed to contain hyphens: a previous revision
# widened them and started firing on ordinary kebab identifiers such as
# `kubectl get pods -n sk-prod-cluster-east-1-services`, which is precisely how
# a hook earns its way onto someone's disable list.
_SHAPES = (
    ("github fine-grained PAT", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("github token", re.compile(r"gh[posru]_[A-Za-z0-9]{20,}")),
    ("gitlab PAT", re.compile(r"glpat-[A-Za-z0-9_]{16,}")),
    # Real Slack tokens carry a long digit run; requiring one keeps prose like
    # `xoxc-not-a-token-just-text` from tripping it.
    ("slack token", re.compile(r"xox[baprsedc]-(?=[A-Za-z0-9-]*[0-9]{6})[A-Za-z0-9-]{16,}")),
    ("slack app token", re.compile(r"xapp-[0-9]-[A-Za-z0-9]{6,}-[0-9]{6,}-[A-Za-z0-9]{16,}")),
    ("aws access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("openai-style key", re.compile(r"\bsk-(?:proj-|ant-|or-)?[A-Za-z0-9]{20,}")),
    ("nvidia key", re.compile(r"\bnvapi-[A-Za-z0-9_]{20,}")),
    ("google api key", re.compile(r"\bAIza[A-Za-z0-9_-]{30,}")),
    ("stripe key", re.compile(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{16,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)

# scheme://user:secret@host
_URL_CREDS = re.compile(r"(?<=://)(?P<user>[^/\s:@]+):(?P<pw>[^/\s@]+)(?=@)")

# name = value / name: value
_ASSIGNMENT = re.compile(
    _L + r"(?i:(api[_\- ]?key|secret|password|passwd|token|credential))" + _R +
    r"(?:[A-Za-z ]{0,24}?)[=:]\s*[\"'`]?"
    r"([A-Za-z0-9/+=_.\-]{16,})"
)

# --token VALUE / --api-key VALUE  -- whitespace-delimited flags never reached
# the assignment tier, and this is the commonest way a credential hits argv.
_FLAG_VALUE = re.compile(
    r"--?[A-Za-z0-9-]*(?i:key|secret|password|token|credential)[A-Za-z0-9-]*"
    r"[= ]\s*[\"'`]?([A-Za-z0-9/+=_.\-]{16,})"
)

# Values that are NAMES or references, not credentials.
_PLACEHOLDER = re.compile(
    r"^\$|^\{\{|^%[A-Za-z_]|"                      # $VAR, {{tpl}}, %VAR%
    r"^(?i:x+|redacted|changeme|replace(_?me)?|your[_-]?\w+|"
    r"username|password|secret|token|value|example|placeholder|test)$"
)
_IDENTIFIER_SHAPES = (
    re.compile(r"^[A-Z][A-Z0-9_]*$"),              # ENV_VAR_NAME
    re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)+$"),  # kebab-or-snake resource name
    re.compile(r"^[A-Za-z0-9_.\-]*/[A-Za-z0-9_.\-/]*$"),   # a path
    # A dotted reference to a name: process.env.TOKEN, __ENV.TOKEN (k6),
    # config.api_key. The ENV_VAR_NAME shape above anchors on [A-Z], so every
    # one of these read as a credential. The dotted shape is safe from raw
    # blobs because it REQUIRES a "." and no base64 alphabet contains one.
    re.compile(r"^_*[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$"),
    # _NAME, __dunder__ -- split by case on purpose. base64url substitutes
    # "-" and "_" for "+/", so "_" IS in that alphabet and a single
    # [A-Za-z0-9_]+ shape exempts any unprefixed base64url token that starts
    # with "_" and happens to contain no "-": measured at 139 of 20000 random
    # 40-char tokens (0.69%). Leading-underscore identifiers are single-case
    # by convention (_SCREAMING_SNAKE or _snake_case) while a base64url blob
    # is mixed-case by construction, so splitting on case takes that 139 to 0
    # while _INTERNAL_API_KEY_NAME, __dunder__ and _private_helper_name all
    # still pass. The cost is a long mixed-case _PascalCaseName read as a
    # credential; this hook advises rather than blocks, so a missed secret
    # costs more than an extra notice.
    re.compile(r"^_+[A-Z][A-Z0-9_]*$"),            # _SCREAMING_SNAKE
    re.compile(r"^_+[a-z][a-z0-9_]*$"),            # _snake_case, __dunder__
)
# Anything matching a real credential shape wins over the name-shaped tests --
# an AWS key id is [A-Z0-9]{20} end to end and would otherwise read as an
# ENV_VAR_NAME, exempting every AWS key id the hook ever saw.
_KNOWN_SECRET = re.compile(
    r"^(gh[posru]_|github_pat_|glpat-|xox[baprsedc]-|xapp-|sk-|[rs]k_|nvapi-|AIza|eyJ)"
    r"|^(AKIA|ASIA)[0-9A-Z]{16}$")


def _is_identifier(value):
    """True when a captured value is a name, reference or placeholder."""
    if _KNOWN_SECRET.search(value):
        return False
    if _PLACEHOLDER.search(value):
        return True
    retval = any(p.search(value) for p in _IDENTIFIER_SHAPES)
    return retval


def findings(command):
    """Return [(label, offset)] for credential-shaped substrings.

    Never returns the matched text itself.
    """
    hits = []
    for label, pattern in _SHAPES:
        for m in pattern.finditer(command):
            hits.append((label, m.start()))
    for m in _URL_CREDS.finditer(command):
        # Skip the form this hook itself recommends: https://user:$TOKEN@host
        if not _is_identifier(m.group("pw")):
            hits.append(("credentials in url", m.start("pw")))
    # (pattern, index of the group holding the VALUE). Explicit rather than
    # m.lastindex, which is Optional and silently shifts if a group is added.
    for pattern, vg in ((_ASSIGNMENT, 2), (_FLAG_VALUE, 1)):
        for m in pattern.finditer(command):
            if not _is_identifier(m.group(vg)):
                hits.append(("secret-shaped assignment", m.start(vg)))
    # De-duplicate by offset: one value reported once, not once per pattern.
    seen, uniq = set(), []
    for label, off in sorted(hits, key=lambda h: h[1]):
        if off in seen:
            continue
        seen.add(off)
        uniq.append((label, off))
    retval = uniq
    return retval


def reason_text(hits):
    """Operator-facing explanation. Shapes and offsets only, never values."""
    shown, extra = hits[:MAX_FINDINGS], max(0, len(hits) - MAX_FINDINGS)
    lines = [
        "This command contains a %s." % REDACT_HINT,
        "",
        "Pass it on stdin so it never reaches the argument vector:",
        "",
        "    KEY=\"$(fetch-it)\" sh -c \\",
        "      'printf \"header = \\\"X-Api-Key: %s\\\"\\n\" \"$KEY\" | curl -K - https://...'",
        "",
        "Referencing it from the environment --",
        "    KEY=\"$(fetch-it)\" sh -c 'curl -H \"X-Api-Key: $KEY\" https://...'",
        "-- keeps it out of the recorded command string, but the inner shell",
        "still expands it into argv before exec.",
        "",
    ]
    for label, offset in shown:
        lines.append("  - %s at offset %d" % (label, offset))
    if extra:
        lines.append("  - ... and %d more" % extra)
    lines += [
        "",
        "Denying does NOT undo a transcript entry -- the command string is",
        "recorded either way. If this is a real credential, rotate it.",
        "",
        "If it is a placeholder or a false positive, approve and carry on.",
    ]
    retval = "\n".join(lines)
    return retval


def respond(decision, reason):
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
            # For "ask", permissionDecisionReason goes to the operator but NOT
            # to the model -- so without this the author of the command learns
            # nothing and retries a near-identical one.
            "additionalContext": reason,
        }
    }
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()


def main():
    mode = os.environ.get("SECRETS_HOOK_MODE", "ask").strip().lower()
    if mode not in ("ask", "deny"):
        return 0
    try:
        payload = json.load(sys.stdin)
        command = (payload.get("tool_input") or {}).get("command") or ""
        if not isinstance(command, str) or not command:
            return 0
        hits = findings(command)
        if not hits:
            return 0
        respond(mode, reason_text(hits))
    except Exception as exc:  # never break a session over this hook
        sys.stderr.write("secrets-hook: skipped (%s)\n" % type(exc).__name__)
    return 0


def selftest():
    """Runnable check: `pre-tool-use.py --selftest`.

    Fixtures are assembled from fragments on purpose: a secret-detector's test
    data looks exactly like secrets, so as literals they trip this repo's own
    pre-publish gate. All values are fabricated.
    """
    ghp = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    xoxb = "xox" + "b-" + "1111111111-2222222222-AbCdEfGhIjKl"
    akia = "AKI" + "A" + "EXAMPLEKEYID1234"
    glpat = "glp" + "at-" + "EXAMPLEEXAMPLEEXAMPLE"
    hexkey = "0123456789abcdef" * 4
    positive = [
        ('curl -H "X-Api-Key: %s" https://example.test' % hexkey, "assignment"),
        ("git clone https://user:%s@host/o/r.git" % ghp, "url + shape"),
        ("export TOK=%s" % xoxb, "shape"),
        ("aws configure set aws_access_key_id %s" % akia, "shape"),
        ("deploy --token %s" % hexkey, "flag value, no vendor prefix"),
        ("export GITHUB_TOKEN=%s" % hexkey, "underscore boundary"),
        ("export DB_PASSWORD=%s" % hexkey, "underscore boundary"),
        ("psql --password %s" % hexkey, "flag value"),
        ("deploy --token %s" % glpat, "shape"),
        # base64url puts "_" in the alphabet, so a leading-underscore token
        # used to pass as an identifier. Mixed case is what distinguishes it
        # from a real _NAME; keep this fixture mixed-case and "-"-free.
        ("deploy --token _%s" % ("Onxa0DLfPPPpPiQMoo_2o7fSGDf3riFjvltHi"),
         "base64url blob starting with _"),
    ]
    negative = [
        ('curl -H "X-Api-Key: $MY_API_KEY" https://example.test', "env ref"),
        ("kubectl get secret my-service-auth-token-dev -o yaml", "resource name"),
        ("echo API key env var is MY_SERVICE_API_KEY", "env var name"),
        ("git log --oneline 2f70d66aa11bb22cc33dd44ee55ff66aa77bb88", "sha"),
        ("docker pull repo@sha256:" + "a1b9b47b" * 8, "digest"),
        ("kubectl get pods -n sk-prod-cluster-east-1-services", "kebab, was a regression"),
        ("echo " + "xox" + "c-not-a-token-just-text-here", "kebab, was a regression"),
        ("git clone https://oauth2:${CI_JOB_TOKEN}@gitlab.test/t/s.git", "the recommended form"),
        ("git clone https://USERNAME:PASSWORD@host/o/r.git", "placeholders"),
        ("curl -X POST https://slack.com/api/auth.test", "plain url"),
        ("const TOKEN = %sENV.SIDEWINDER_TOKEN || ''" % ("_" * 2), "k6 env ref"),
        ("const token = process.env.SERVICE_TOKEN", "dotted env ref"),
        ("echo api_key = %sINTERNAL_API_KEY_NAME" % "_", "underscore-prefixed"),
        ("echo api_key = %sinternal_api_key_name" % "_", "underscore, lower"),
    ]
    bad = 0
    for cmd, why in positive:
        if not findings(cmd):
            print("MISS  (%s) %s" % (why, cmd[:60]))
            bad += 1
    for cmd, why in negative:
        hits = findings(cmd)
        if hits:
            print("FALSE POSITIVE (%s) %s -> %s" % (why, cmd[:52], hits))
            bad += 1
    print("selftest: %d positive, %d negative, %d problem(s)"
          % (len(positive), len(negative), bad))
    retval = 1 if bad else 0
    return retval


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
