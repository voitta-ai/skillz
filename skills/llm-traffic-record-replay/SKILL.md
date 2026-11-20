---
name: llm-traffic-record-replay
description: |
  Build a regression check for a backend that calls LLMs by recording a real
  run's traffic and replaying it with no model. Use when: (1) server code
  (edge functions, workers) calls an OpenAI-compatible gateway and a change to
  a gate, guard, fallback or prompt must show before anyone runs a paid call;
  (2) a replay leaves the path of the recorded run (a request "the recording
  does not hold") on unchanged code; (3) a recording replays on one database
  and not on another; (4) you must show that the replay check is not vacuous.
  Covers two recording proxies, a baseline taken from a frozen run instead of
  the live one, answering concurrent model requests in recorded finish order,
  late-arriving requests and persistent connections, caches and unordered
  rows as hidden state, the four outcomes of a request, and the mutation
  checks that prove it works.
author: Claude Code
version: 1.0.0
date: 2026-11-19
source: https://github.com/voitta-ai/skillz
source_file: skills/llm-traffic-record-replay/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/llm-traffic-record-replay/SKILL.md`). Updates go through the
> repo's worktree + PR workflow - open an issue, branch, PR.

# Record an LLM backend's traffic and replay it with no model

## Problem

A backend asks a model, then runs code on the answer: gates, guards,
fallbacks, thresholds. Unit tests cover the pieces. Nothing covers a whole
run, because a model does not answer the same way twice and every run costs
money. So a change to one rule quietly breaks another path, and nobody sees.

A recorded run fixes both: the model's answers come from a file. But the
first replay of a real system does not match the run it was recorded from.
The reasons are few, and each has a known cure.

## Context / Trigger Conditions

- A client (browser, script) calls server functions, and those call a model
  gateway over HTTP. The functions keep little or no state between requests,
  or the client sends the state with each request.
- You can point the client at another base URL, and the functions at another
  gateway URL, without changing their code.
- Symptoms this skill explains: a replay asks the model something that was
  never recorded; two replays of unchanged code differ; a recording replays
  on the database it was made on and nowhere else.

## Solution

### 1. Record at two boundaries, with two proxies

- **Client to functions.** A pass-through proxy in front of the backend. Save
  method, path, request body, status and response body of every function
  request, numbered when it *starts*. Do not save request headers: the
  sign-in token is there.
- **Functions to model.** A proxy where the gateway URL points. Save the
  request body and the whole answer, with start and finish times. Keep the
  answer as the gateway gave it. Functions read more than the text (the model
  name, the finish reason), and the cost fields let you price the run.

Send `Accept-Encoding: identity` upstream so that what you save is text.
Scan the result for tokens before you commit it. A base64 string that starts
`eyJ` is not always a token: decode one before you panic.

A gateway names the account in the answer when it refuses a request (a rate
limit, no credit): `"user_id":"user_..."`. Successful answers do not carry
it, so a clean run hides this. Take such ids out of the answers when the
recording is written, by key name and by the shape of the id, and leave the
requests alone: the replay finds an answer by its request.

### 2. Replay sequentially, and take the baseline from a replay

Send the recorded function requests again one after the other, in the order
they started. The model proxy answers a request when it equals a recorded
one (hash of the canonical JSON), and returns a distinct error status when it
does not. After each function request, ask the proxy which recorded answers
it served and what it missed.

The baseline is the output of a frozen run, not of the live run. A live run
has concurrency and slow models that a frozen run does not have. Accept a
recording only when two frozen runs in a row agree, and refuse it when any
request misses on unchanged code.

Two runs are the routine check for one recording. They do not show that the
replay itself can be trusted: for that, see Verification.

### 3. Answer concurrent requests in the order the recording finished them

This is the step that is not obvious. Code decides by the order in which
answers come back, and answers from a file come back at once.

- A function asks a second model when the first is slow and takes the first
  usable answer. With instant answers the first model always wins. If the
  live run was won by the second, the replay carries another line forward,
  and the next model request (a judge, a rewrite) is one the recording never
  saw.
- A function sends three drafts side by side and uses the first that passes
  its checks. These have different prompts, so "the same question asked of
  several models" does not find them.

The rule that held:

- **Any requests that are open at the proxy together are answered in recorded
  finish order.** A request waits for every request that overtook it in the
  recorded run. In a sequential replay, requests that are open together
  belong to one function call.
- **Wait for a request that has not arrived only if it is a sibling:** the
  same system prompt, and sent within a few seconds of this one in the
  recording. A later turn reuses the system prompt and is not a sibling;
  waiting for every overtaker made a run three times as long.
- A sibling the recording sent *after* this request is sent by a timer in the
  function: wait until the moment it was due, plus a margin, then stop. If
  the code no longer sends it, the replay must end, not hang.
- A sibling the recording sent *before* this request is on its way: wait a
  few seconds for it.
- A request that asks a recorded question of a model the recording did not
  ask is a race that went one model further. Hold it until that question is
  answered, give it no answer, and fail the function request as different.
- Leave a few tens of milliseconds between two answers, and give every wait
  a hard ceiling.

Cost: a race a later model won takes as long as the timer that sends it.

Limit: streams are replayed whole. If the code acts when a field inside a
stream closes, the live order of those moments is not in a recording that
keeps only start and finish times. Record the time of each piece if you need
it.

### 4. Find the hidden state

Each of these made a replay differ from its recording or from another replay:

| State | Cure |
|---|---|
| A cache in the function's memory | Restart the function runtime before each run |
| A cache in a table with a time-to-live | Delete the fresh rows before each run, and before recording |
| Rows read with `ORDER BY` on a key that has ties | The order follows the heap layout; any `UPDATE` reshuffles it. Run on a database built from nothing, and fix the query with a unique second key |
| A model request made after the response (`waitUntil`) | After each function request, wait until the proxy has been idle for a short time |
| A date written into a prompt | Replace it with a placeholder before hashing; add a pattern only when a replay shows the need |
| A new connection for every model request | Keep connections open in the replay proxy (HTTP/1.1, a Content-Length on every answer). See below |
| Durations in responses | Drop those keys before comparing |

To learn what a run writes, hash every table before and after, and compare.
Do not trust a list read from the code. For one table:

```sql
select count(*), md5(coalesce(string_agg(t::text, E'\n' order by t::text), ''))
from public.some_table t;
```

**The connection trap.** A proxy that closes each connection after one
answer makes the functions open hundreds of connections in a run. From
containers to a proxy on the host, about one attempt in several hundred did
not get through at once: a request arrived 1 second late, 4 seconds late,
once 67 seconds late, which fits a connection attempt retried at 1, 2, 4, 8,
16 and 32 seconds. A race then ends the other way, and one replay in four or
five differs from the rest. It looks like a bug in the ordering rule and is
not. With connections kept open, ten runs in a row agreed. Give each run its
own proxy log with times: the late arrival is plain to see there.

### 5. Four outcomes for a request

- **same**: it asked the baseline's questions and its response is equal.
  Compare the questions (the messages), not the requests: how many models a
  question reaches depends on timers and differs between runs.
- **different**: every question was answered, and the response or the list
  of questions differs. Code outside the model changed. Fail the run.
- **prompt changed**: a model request missed. Show the closest recorded
  request and the lines that changed. If the lines are the same in another
  order, say so in one line: that is the tie order above, not a wording change.
- **unstable**: two runs of unchanged code disagreed when the recording was
  accepted. Report it and do not compare it. Never drop it silently.

### 6. Prove that the check is not vacuous

"Everything is the same" is also what a broken replay prints. Before you
trust it, make each of these fail the way it should:

1. Change one recorded *answer* in a copy of the recording: that request, and
   no other, comes out as different.
2. Change one recorded *request* in a copy: that request comes out as prompt
   changed, with the changed line.
3. Change a threshold in real code on a throwaway backend: the requests past
   the threshold fail and none before them.
4. Make a function skip its model request: it fails even where its response
   text is unchanged.
5. Replay on a second backend built from nothing. If it differs there, the
   recording depends on the state of one machine.
6. Give the tools a self-test that needs no backend: a stub function that
   asks a second stub model when the first is slow, recorded and replayed
   with the same proxies. One of its checks is that the replay ends the race
   as the recording did. Switch the ordering of step 3 off and watch that
   check fail.

## Verification

- When the replay is new, or its ordering has changed, ten frozen runs of
  the longest recording agree, not two: a fault that shows in one run of
  five passes a pair of runs more often than not. After that, the two runs
  of step 2 are enough to accept a recording.
- The responses of a frozen run equal those of the live run once durations
  are dropped, or you can say why the rest differ.
- The six checks above each fail as described.
- The sum of the answers' cost fields equals the change in the key's usage
  counter. Read the key's remaining limit before you record.

## Example

A call-coaching backend: 28 function requests and 54 model requests in one
recorded call. The first replay missed in 3 requests. In each, the closer's
line had been asked of three models; the second had won the live race; and
the replay took the first model's reply, which the token limit had cut to
three words. With races replayed in finish order, the replay matched the live
call in all 28 responses and took 13 seconds. A later test updated one rule
row and restored its text: 21 of 28 requests then sent a prompt with the same
rules in another order, because 130 of 190 rows shared a sort key.

A whole call of 173 function requests and 319 model requests then replayed
differently about one run in five. Two causes: three drafts with different
prompts raced, and a request arrived late. With concurrent requests ordered
and connections kept open, ten runs in a row agreed in all 173 requests, at
76 seconds a run; 168 responses equalled the live call's.

## Notes

- Compress recordings with xz, not gzip. Prompts repeat across requests
  farther apart than gzip's window: 2.7 MB became 78 KB with xz and 913 KB
  with gzip.
- A recording holds the prompts. Treat it like the prompt source itself.
- Play the recorded run in a headless browser. A tab in the background
  throttles timers, and an app may rebuild its page when the tab returns;
  the first recording here ended after seven turns that way.
- A new model account may be rate limited. Refused requests end up in the
  recording as real failures; decide whether that is the run you want.
- Do not test a database mutation on the developer's working stack. Build a
  second stack for it, or save the row and the table hash to a file first.
- This checks code around the model. Whether a *changed* prompt still gets
  good answers needs a live run and checks a person approves.

## Related

- `agent-eval-replay-history-leak` - another replay eval and the way its
  answer leaks.
- `supabase-local-stack-unreplayable-migrations` - building the local backend
  that a replay runs against.
- `agent-traffic-log` - logging an agent's own traffic.
