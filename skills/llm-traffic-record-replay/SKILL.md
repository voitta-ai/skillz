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
  the live one, replaying a race between models in recorded finish order,
  background model requests, caches and unordered rows as hidden state, the
  four outcomes of a request, and the mutation checks that prove it works.
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

### 3. Replay a race between models as it ended

This is the step that is not obvious. Code that asks a second model when the
first is slow, and takes the first usable answer, behaves differently when
answers come at once: the first model always wins. If the live run was won by
the second model, the replay now carries another line forward, and the next
model request (a judge, a rewrite) is one the recording never saw.

- **Recognise a race from the recording:** requests with the same `messages`
  whose time windows overlap. They differ only in `model` and its limits.
- **Answer them in recorded finish order.** Hold a request until every
  request that overtook it in the recorded run has had its answer.
- **An overtaker that has not arrived yet** is sent by a timer in the
  function. Wait for it until the moment it was due (its recorded start
  offset from the first request of the race, plus a margin), then stop
  waiting. If the code no longer sends it, the replay must end, not hang.
- Leave a few tens of milliseconds between two answers of one race, and give
  every wait a hard ceiling.

Cost: a race the second model won takes as long as the timer that sends it.

### 4. Find the hidden state

Each of these made a replay differ from its recording or from another replay:

| State | Cure |
|---|---|
| A cache in the function's memory | Restart the function runtime before each run |
| A cache in a table with a time-to-live | Delete the fresh rows before each run, and before recording |
| Rows read with `ORDER BY` on a key that has ties | The order follows the heap layout; any `UPDATE` reshuffles it. Run on a database built from nothing, and fix the query with a unique second key |
| A model request made after the response (`waitUntil`) | After each function request, wait until the proxy has been idle for a short time |
| A date written into a prompt | Replace it with a placeholder before hashing; add a pattern only when a replay shows the need |
| Durations in responses | Drop those keys before comparing |

To learn what a run writes, hash every table before and after
(`md5(string_agg(t::text, ... order by t::text))`). Do not trust a list read
from the code.

### 5. Four outcomes for a request

- **same**: it made the baseline's model requests and its response is equal.
- **different**: every model request was answered, and the response or the
  list of requests differs. Code outside the model changed. Fail the run.
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
6. In the tool's own self-test (a stub function and a stub model), switch the
   race handling off and watch the race check fail.

## Verification

- Two frozen runs agree, and the responses of a frozen run equal those of the
  live run once durations are dropped.
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

## Notes

- Compress recordings with xz, not gzip. Prompts repeat across requests
  farther apart than gzip's window: 2.7 MB became 78 KB with xz and 913 KB
  with gzip.
- A recording holds the prompts. Treat it like the prompt source itself.
- Record with the client's fastest mode. A browser tab in the background
  throttles timers, and a UI that paces itself with animation stalls.
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
