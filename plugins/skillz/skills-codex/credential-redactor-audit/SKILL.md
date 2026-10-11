---
name: credential-redactor-audit
description: |
  Audit a credential-redaction or secret-detection layer you own, and clean
  up what it already leaked. Use when: (1) you wrote or are reviewing code
  that strips secrets out of logs, telemetry, transcripts, error reports or
  crash dumps; (2) a redactor "has tests" and you need to know whether they
  prove anything; (3) you shipped redaction and realise it only applies to
  NEW writes, so existing files are still plaintext; (4) you need to verify
  a scrub without printing the secrets you are hunting; (5) a secret
  detector is producing false positives and is about to be switched off.
  Covers the failure modes that survive a normal test suite: fixtures that
  hide the bug, fixture values shorter than the real credential format,
  structured patterns that bypass the value guard, span merging that drops
  overlaps instead of clipping, non-idempotence that invalidates "re-scan
  and expect zero", allow-lists that reject high-entropy values, redact-
  then-truncate window shifts, fixing one sink of N, and a "fail loudly"
  import that is actually silent and fail-open. This is about the filter's
  own correctness. For auditing a git repo before open-sourcing it see
  pre-open-source-credential-audit; for hunting the copies a secret already
  scattered across local disk see agent-credential-leak-surfaces.
author: Claude Code
version: 1.1.0
date: 2026-08-15
---

# Auditing a credential-redaction layer

## Problem

A redactor is a filter whose failures are invisible. When it works you see
nothing; when it silently misses, you also see nothing — until the secret
turns up in a log during an incident. Ordinary test suites are especially
weak here, because the natural fixtures are the ones the author already had
in mind.

This is drawn from four adversarial review rounds against one redactor
(`voitta-ai/voitta-yolt`, issues #84–#93). Every round found real leaks in
code whose tests were green, including two rounds *after* the fix for the
previous round. The regexes are not the reusable part. The failure modes
are.

## Context / Trigger Conditions

- You are writing or reviewing code that removes secrets from any text that
  gets persisted or transmitted.
- Someone says "we redact that" and you want to know what that means.
- Redaction shipped, and you have log files from before it.
- A secret detector is noisy enough that people are talking about disabling
  it.

## Part 1 — Failure modes to attack

Work through these in order. Each has bitten a real implementation.

### 1. Fixtures that hide the bug

A pattern that cannot match its own keywords still passes a suite whose
fixtures all carry a prefix.

```
\b[A-Za-z_][A-Za-z0-9_]*(?:TOKEN|SECRET|PASSWORD|...)\s*=
```

requires **at least one character before the keyword**. So `GH_TOKEN=`
matched and bare `TOKEN=` did not — every keyword failed to match itself.
The tests used `SERVICE_TOKEN=` and `AWS_KEY=`, and were green.

> **Rule: exercise every alternation branch standalone.** If a pattern
> lists ten keywords, the suite needs ten single-keyword cases, not one
> composite case.

### 2. Fixture values shorter than the real format

```
npm_[A-Za-z0-9_\-]{16,}
```

looked correct against a hand-written fixture of `npm_` + 32 characters.
Real npm tokens are `npm_` + 36, and the loose `{16,}` also matched npm's
own environment variables — `npm_config_*`, `npm_package_*`,
`npm_lifecycle_*` — which appear in every CI log on the platform.

> **Rule: fixtures must be real-format length.** A short fixture makes an
> over-loose pattern look tight. Look up the actual vendor format; do not
> invent a plausible-looking one.

### 3. Structured patterns bypass the value guard

Most redactors have two families: self-identifying prefixes (`ghp_`,
`AKIA`) matched anywhere, and contextual shapes (`--token X`,
`Authorization: X`) where a *guard* decides whether the captured value
looks like a literal.

The prefix family usually skips the guard entirely — there is nothing to
tune behind it. A loose prefix therefore has **no safety net at all**,
which is why #2 above went straight to production.

> **Rule: any pattern that bypasses the guard needs its false-positive
> corpus doubled, because a mistake there is unrecoverable at runtime.**

### 4. Span merging that drops overlaps instead of clipping

Given overlapping matches, the naive merge keeps a span only when
`start >= reach`. A span that *starts inside* its predecessor but *ends far
beyond it* is then discarded entirely:

```
ssh-add --password abc123def456ghi789-----BEGIN RSA PRIVATE KEY-----
BODYSECRETMATERIAL
-----END RSA PRIVATE KEY-----
```

The flag capture took `abc123def456ghi789-----BEGIN`; the private-key span
started inside it and was dropped. Output:
`--password [REDACTED:flag-value]` followed by the entire key body in
cleartext — with a marker that makes the record *read as handled*.

Clip instead:

```python
for start, end, kind in spans:          # sorted by (start, -end)
    if end <= reach:
        continue                        # fully covered
    start = max(start, reach)           # clip to the uncovered tail
    out.append((start, end, kind))
    reach = end
```

> **Property test it.** Generate span sets exhaustively over a small
> position space plus randomised larger ones, and assert four invariants:
> `start < end`, output sorted, output non-overlapping, and **union
> coverage preserved versus input**. That last one is what makes clipping
> *correct* rather than merely different.

### 5. Non-idempotence, which invalidates your verification method

The obvious way to verify a scrub is "re-scan and expect zero hits". That
is only valid if `redact(redact(x)) == redact(x)`.

It usually is not, because the patterns match inside the markers the
redactor itself emits. A URL-credentials pattern happily reads
`[REDACTED:api-key]` as a password field. Two distinct bugs:

- a span **entirely inside** a marker → skip it;
- a span that **contains** a marker plus surrounding text → judge the
  *residue* with markers removed, and skip if that residue is not itself
  secret-shaped.

Only fixing the first leaves 1.3% of a fuzz corpus non-idempotent — enough
that a verification pass reports a pile of phantom hits and you go hunting
ghosts.

Also pin the marker pattern to the **closed set of kind names**, ideally
built from the pattern table itself. A permissive `\[REDACTED:[a-z0-9-]+\]`
is *also the shape of a lowercase-hex key*, so
`TOKEN=[REDACTED:9f3c1a7e...]` reads as a marker and the value survives.

### 6. Guard character allow-lists run backwards

```python
re.fullmatch(r"[A-Za-z0-9_\-.+/=~:%]+", value)   # "does it look like a key?"
```

This excludes `! @ # , & { }` and space — so the **more punctuation a
password has, the more entropy, the likelier it is dismissed as
"not secret-shaped"**. `Tr0ub4dor&3!SuperLongPassword` sailed through while
`some-resource-name` was redacted.

> **Rule: the character test must be a deny-list, not an allow-list.**
> Reject what proves the value is *not* a literal — shell expansions
> (`$VAR`, `$(...)`, backticks) — and say nothing about which characters a
> secret may contain.

### 7. Length is the wrong axis for "is this a name or a key"

A long all-alpha passphrase and a long all-alpha English word are
structurally the same string, so no length bound separates
`CORRECTHORSEBATTERYSTAPLE` from `authenticationprovidername`. Do not
conclude it is unfixable — use the *alphabet* instead:

- **all-hex ≥ 20 chars** → a key, regardless of length. This is what a low
  length bound is usually approximating, badly.
- **lowercase kebab-case with alphabetic segments** → a resource-name
  idiom (`production-deployment-approval`), never a credential literal.
- length bound only for what remains.

### 8. Redact-before-truncate shifts the truncation window

If you truncate for line-length (`value[:500]`), redact **first** — a
secret straddling the cut must not be half-written.

But be aware of the converse: redaction *shortens* the string, so text that
truncation used to discard moves **into** the window. A long PEM collapsing
to a marker can pull a previously-cut password into view. This is not an
argument for truncate-first (that reintroduces half-written secrets); it is
an argument for not treating truncation as a security boundary.

### 9. Fixing one sink of N

Enumerate every place the sensitive text is written before fixing any of
them. One implementation redacted the `examples` field of a report and left
the sibling `glob_collisions` field, which rendered into the *same two
files*, producing the same credential redacted on one line and cleartext
eight lines below.

The one that gets missed is often the *more* dangerous one: there, a
"collision" was by definition a non-safe command, i.e. exactly the
`-X POST ... -H 'Authorization: ...'` shape.

> **Rule: assert that no raw secret reaches *any* produced artifact.** A
> per-field assertion is what lets sink N+1 through.

```python
for path in produced_files:
    assert FAKE_TOKEN not in path.read_text()
```

### 10. "Fail loudly" that is silent and fail-open

An unguarded import justified by a comment — *"if the redactor cannot load,
failing loudly beats silently writing credentials"* — was measured and did
neither. `ModuleNotFoundError` exits 1; in that host a non-zero non-2 exit
was **non-blocking**, and stderr was not surfaced. Result: the tool ran with
no analysis, wrote nothing, and told nobody.

> **Rule: measure what your failure path actually does in the host that
> invokes you.** Then degrade explicitly: keep the parts that never needed
> the redactor, and write a placeholder such as
> `[WITHHELD:redactor-unavailable]` plus an error field — visible, and
> incapable of leaking.

### 11. One detector shared between "redact" and "warn"

If the same matcher powers both log redaction and a user-facing warning,
then on any input it misses the user gets a leak **and** an affirmative
silence that reads as "checked, nothing here". Say so in the docs; two
layers that share a detector are one layer.

## Part 2 — Scrubbing what already leaked

Redaction almost always ships **write-time only**, so every record written
before it is still plaintext. That is the half people forget, and it is the
half a leak investigation actually finds.

**Rewrite in place; do not truncate.** Truncating destroys the operational
value of the logs and is rarely necessary — running existing records
through the redactor preserves every record and removes only the values.

```python
# Dry-run by default; --apply to write.
for line in path.read_text().splitlines():
    record = json.loads(line)
    for field in ("command", "reason"):
        record[field] = redact(record[field])
    out.append(json.dumps(record))

if len(out) != len(lines):
    raise SystemExit("refusing to rewrite: line count changed")
tmp.write_text("\n".join(out) + "\n")
tmp.replace(path)          # atomic
```

Guards that matter: dry-run first, a line-count check before replacing, and
an atomic rename.

**Filter your own markers when verifying.** The obvious check — re-scan and
expect zero — reports the redactor's own output as hits unless you both fix
#5 above and exclude markers explicitly:

```python
real = [(s, e, k) for s, e, k in find_secrets(text)
        if not text[s:e].startswith("[REDACTED:")]
print(f"{path.name}: {len(real)} spans remaining")
```

Skipping this sent one investigation chasing 93 phantom hits.

**Sweep every artifact the log feeds, not just the log.** Anything
downstream that copied it — generated reports, state files, caches, issue
drafts — holds its own copy with its own lifetime, and a regeneration step
will refill them from the still-plaintext history. Fixing the writer
without scrubbing the derived files means the exposure keeps growing.

For the wider question of *where else* a secret has already landed on the
machine, and for reporting a suspect value without echoing it, use
**`agent-credential-leak-surfaces`** — it covers the surface inventory and
the fingerprint-not-echo technique, and this skill does not duplicate them.

## Verification

You are done when all of these hold:

- every alternation branch has a standalone test;
- a false-positive corpus of realistic ordinary commands/records survives
  **byte-for-byte**, and grows with every widening;
- span merging passes a union-coverage property test;
- `redact(redact(x)) == redact(x)` over a fuzz corpus, including inputs
  that already contain markers;
- re-scanning redacted text yields zero non-marker hits;
- no raw secret appears in **any** produced artifact, asserted file-wide;
- the missing-redactor path is exercised by an actual test (delete the
  module and run the entry point);
- pathological inputs are timed, not assumed — quadratic regex behaviour
  hides behind small test inputs.

## Notes

- Prefer **over-redaction**: a false positive costs one unreadable value in
  a debug log; a false negative costs a credential on disk forever. Say
  this in the code, then check the code actually does it — the allow-list
  in #6 claimed exactly this while doing the opposite.
- Redaction narrows blast radius. It does not make it safe to put a
  credential on a command line, where `argv` is readable by anything that
  can run `ps`.
- Keep the *shape* wherever possible (`--token [REDACTED:flag-value]`
  rather than dropping the whole argument). Downstream tooling usually
  mines shapes, and a shaped record stays diagnosable.
- Adversarial review of a redactor is worth repeating **after** each fix.
  Three of the four rounds cited here found holes introduced or left by the
  previous round's fix.

## Scan `toolUseResult.bashEditDiff`, element by element

A transcript audit that reads only `message.content` misses an entire class of
leak. When a Bash command writes a **git-tracked** file, the harness records a
before/after diff at `toolUseResult.bashEditDiff.files[].hunks[].lines` - so the
secret is in the transcript although nothing the agent typed contains it.

Each diff line is a separate JSON array element, so a PEM header and its body
are **never adjacent in the raw text**. A regex looking for a header followed by
base64 in one string reports "no body" and is wrong. Walk `hunks[].lines`
element by element.

Observed 2026-09-30: 25 base64 lines of an old committed key plus 25 of a newly
generated one, present under `toolUseResult` and absent from `message.content`.

See `agent-credential-leak-surfaces` surface 7 for the remediation, which is
user-run: the agent cannot scrub its own transcript.

## References

- Origin: `voitta-ai/voitta-yolt` issues #84, #85, #89, #90, #91, #92, #93
  and PRs #86, #88, #94, #95.

## Related

Three skills, three different objects:

- **this one** — the *filter*. Does your redactor actually redact?
- `agent-credential-leak-surfaces` — the *machine*. Where has a secret
  already been copied, and how do you report it without echoing it?
- `pre-open-source-credential-audit` — the *repository*. Tracked files plus
  full history, before flipping it public.

Reach for this one when you own the redaction code. Reach for the other two
when you own the mess.
