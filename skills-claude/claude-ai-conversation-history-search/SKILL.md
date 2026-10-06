---
name: claude-ai-conversation-history-search
description: |
  Search your own past claude.ai conversations for something you said or were
  told. Use when: (1) you need to find or disprove a claim about what was said
  in an earlier Claude chat, (2) you want to grep your whole Claude history,
  (3) someone references "that chat we had" and you need the receipts,
  (4) you tried grepping ~/Library/Application Support/Claude and found nothing,
  (5) a claude.ai export arrived as a manifest JSON instead of a data zip, or
  (6) curl on an export URL returns HTTP 403 with a Cloudflare
  "Just a moment..." page. Covers the export request flow, the multi-file
  manifest with one-time URLs, and searching conversations.json.
author: Claude Code
version: 1.0.0
date: 2026-08-19
---

# Searching Your Own claude.ai Conversation History

## Problem

You need to find (or prove the absence of) something in a past claude.ai
conversation. The obvious move — grep the local disk — returns nothing, and it
is easy to conclude the chat doesn't exist when in fact you looked in a place
that never had it.

## Context / Trigger Conditions

- "Show me where I said X" / "you said X in that Claude chat"
- You want to search all your Claude conversations at once
- `grep -ri 'something' ~/Library/Application\ Support/Claude/` returns nothing
- Your export download is a small `manifest-*.json`, not the data
- `curl` on an export URL returns `HTTP 403`, `text/html`, and a body starting
  `<!DOCTYPE html><html...><title>Just a moment...</title>`

## Solution

### Step 0 — Know that local disk is a dead end

**Claude Desktop is a thin client and persists no conversation transcripts to
disk.** Verified by grepping all of `~/Library/Application Support/Claude` and
`Claude-3p`: Cookies, Local Storage, IndexedDB and caches hold session state,
not messages. Claude Code's `~/.claude/projects/**/*.jsonl` holds only Claude
Code sessions — a different product, not your claude.ai chats.

Do not spend time on local archaeology. Skip to the export.

### Step 1 — Free pre-check (optional, ~2 min)

Use the in-app search in Claude Desktop / claude.ai. A hit ends the task
immediately. A miss proves **nothing** — in-app search matches titles and only
some content — so never treat it as a negative result.

### Step 2 — Request the data export

claude.ai or Claude Desktop → your avatar (bottom-left) → **Settings** →
**Privacy** → **Export data**. Anthropic emails a download link. Arrival is
minutes to ~24h; start it early and do other work meanwhile.

**Do this once per account.** Personal and work/company logins are separate
orgs with separate histories — request from each, and check the `users.json`
in each zip to confirm which account you actually got.

### Step 3 — Handle whichever of the two shapes arrives

**Shape A — a single data zip**, e.g.
`data-<org-uuid>-<ts>-<hash>-batch-0000.zip`. Contains everything:

```
users.json  memories.json  login_history.json
projects/<uuid>.json  conversations.json      <-- the one that matters
```

**Shape B — a manifest**, e.g. `manifest-<org-uuid>-<ts>-<date>.json`. This is
**not your data**; it is an index of separate downloads:

```json
{
  "instructions": "Download each file using the export_url. Note: Each export URL can only be used once.",
  "total_files": 4,
  "data_files": [
    {"category": "light_metadata", "export_url": "https://claude.ai/export/<org>/download/<token>"},
    {"category": "projects",       "export_url": "..."},
    {"category": "memories",       "export_url": "..."},
    {"category": "conversations",  "export_url": "..."}
  ]
}
```

Print the URLs and open the `conversations` one in a **browser**:

```bash
python3 -c "
import json,sys
d=json.load(open(sys.argv[1]))
for f in d['data_files']:
    print(f\"{f['category']:<16} {f['export_url']}\")
" manifest-*.json
```

**Open these in a browser, not curl.** The endpoint sits behind Cloudflare;
curl gets `HTTP 403` and a `Just a moment...` interstitial. Useful detail: a
*challenged* request does **not** consume the one-time URL, so a failed curl is
recoverable — but there is no reason to spend the attempt. If a URL does get
burned, just request a fresh export.

### Step 4 — Search

`scripts/search_claude_export.py` (in this skill) takes a zip or a
`conversations.json` plus one or more case-insensitive regexes, and walks
**every string** in the JSON rather than modeling the schema — the export shape
has changed before, and a missed key is a false negative.

```bash
./scripts/search_claude_export.py conversations-000.zip 'empathy' 'ur.?fascism'
./scripts/search_claude_export.py conversations.json 'the exact phrase'
./scripts/search_claude_export.py --selftest
```

Exit code is 0 on hits, 1 on none. For "which conversations mention both A and
B", flatten each conversation and test membership rather than regexing twice.

### Step 5 — Search for the *idea*, not just the words

The literal phrase you remember is usually not the phrase that was typed. Widen
to the surrounding concepts, proper nouns, and any framework or artifact the
conversation was built around. A person recalling "you said X about Y" is often
remembering an *output* — a chart, a rating, a list — so search for the thing
that produced it, not for X.

## Verification

Confirm you searched what you think you searched:

```bash
python3 -c "
import json,sys
d=json.load(open(sys.argv[1]))
print('conversations:', len(d))
ds=sorted(c.get('created_at','') for c in d if c.get('created_at'))
print('range:', ds[0], '->', ds[-1])
" conversations.json
cat users.json    # which account is this?
```

Check the **date range** before reporting a negative — but do not assume the
latest timestamp is an export cutoff. A max `created_at`/`updated_at` of "two
weeks ago" usually just means you started no new conversation since then. Two
cross-checks separate truncation from inactivity:

```bash
# 1. When was the export actually generated? (epoch is in the zip filename)
python3 -c "import datetime;print(datetime.datetime.fromtimestamp(<epoch>, datetime.UTC))"

# 2. Was there account activity after the apparent cutoff?
python3 -c "
import json
r=json.load(open('login_history.json'))['login_events']
ts=sorted(x['timestamp'] for x in r)
print('logins:', ts[0][:19], '->', ts[-1][:19])
"
```

If the export is fresh and `login_history.json` shows logins past the last
conversation date, the snapshot is complete and the gap is real inactivity —
logging in (including Claude Code OAuth) does not create a conversation. Say
"coverage is complete", not "there may be a gap".

## Example

Searching for an alleged statement across two accounts:

- Personal (`data-*.zip`): 343 conversations, 2024-10-26 → 2026-08-01. Three
  hits on `empathy`+`trump`, all noise — "craft *trumps* ideology" as a verb,
  and fetched web-page text quoted into the chat.
- Work (manifest → `conversations-000.zip`): 4 conversations, all technical,
  0 hits.

Reported as: not present in either account, with the 2026-08-01 cutoff and the
substring false positives named explicitly.

## Notes

- **Substring false positives** wreck naive greps: `celine` matches
  Mar**celine**, compliance**line**, source**line**; `trump` matches
  "trumps ideology". Always print surrounding context and read the hits.
- **Pasted/fetched web content lives in the transcript.** A keyword can appear
  in a conversation because Claude fetched a page containing it, not because
  anyone said it. Check whether a hit is authored text or quoted material.
- A negative result across your own accounts cannot refute a claim about a chat
  on **someone else's** account, or a screenshot. Say so rather than
  overclaiming.
- Sibling gotcha when local files are blocked by macOS TCC rather than absent:
  the app needing Full Disk Access is the one at the top of the process
  ancestry, which `$TERM_PROGRAM` may misreport. Walk the PPID chain.
