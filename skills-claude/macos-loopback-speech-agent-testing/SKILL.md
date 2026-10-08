---
name: macos-loopback-speech-agent-testing
description: |
  Drive and verify a live speech-to-text agent (continuous capture -> VAD /
  level segmentation -> Whisper -> LLM) end to end on macOS with no human
  speaking, then harden it for a real microphone. Use when: (1) you built or
  changed a listener that captures from an audio device and need a
  repeatable end-to-end test, (2) you want a scripted, recordable demo of a
  voice agent, (3) the first utterance after start comes out garbled or
  missing, (4) the transcript shows "Thank you.", "You", or one phrase
  repeated for a whole line when nobody said it, (5) proper nouns come out
  wrong (an account name heard as a similar common phrase), (6) it works on the loopback
  device but "does not react" on the real mic. Covers BlackHole + `say -a`
  injection, readiness gating, model warm-up, Whisper phantom filtering
  (including large-v3-turbo reporting no_speech_prob 0 on everything),
  vocabulary prompts, and the mic-path differences.
author: Claude Code
version: 1.0.0
date: 2026-10-05
source: voice-agent build session (live listener + Slack hand-off)
source_file: skills/macos-loopback-speech-agent-testing/SKILL.md
---

# macOS loopback speech-agent testing

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/macos-loopback-speech-agent-testing/SKILL.md`). Updates go through
> the repo's worktree + PR workflow.

## Problem

A live listener only fails in ways you can see when audio actually flows
through it: device selection, segmentation, transcription, the relevance
gate, the output. Testing it by talking to it is slow, unrepeatable and
impossible from an agent session. And the defects that matter most -- the
first utterance after start, invented text on silence, misheard names -- only
show up end to end.

## Context / Trigger Conditions

- A process captures from an input device (sounddevice / PortAudio,
  ffmpeg avfoundation, ...) and transcribes locally (mlx-whisper,
  faster-whisper, whisper.cpp) before handing text to a model.
- You need a test or demo that runs without a person, from a script.
- Symptoms on the real mic: phantom "Thank you." lines, a long repeated
  phrase, a misheard proper noun, or nothing at all.

## Solution

### 1. Inject speech through a loopback device

Install BlackHole (2ch). macOS `say` can write straight to an output device:

```bash
say -a "BlackHole 2ch" "Agent, is the order still open?"
say -v Milena -a "BlackHole 2ch" "..."    # other languages: `say -v '?'`
say -a "BlackHole 2ch" -r 260 "..."       # fast speech, a harder case
```

Point the listener at `BlackHole 2ch` as its input. Nothing plays on the
speakers and no system output routing changes. For a test that must exercise
the relevance gate, script *both* kinds of line: things it must ignore (small
talk, people talking to each other) and things it must act on.

### 2. Gate the script on readiness, not on a sleep

Have the listener print one line when it is really listening (model loaded,
stream open), and have the driver wait for it:

```bash
./run.sh "$@" 2> >(tee "$LOG" >&2) &
until grep -q "listening on" "$LOG"; do kill -0 $! || exit 1; sleep 1; done
while IFS= read -r line; do say -a "BlackHole 2ch" "$line"; sleep 3; done < demo.txt
```

One line per utterance, a gap longer than the end-of-utterance silence, and
a tail long enough for the last model call. The same script is the demo.

### 3. Warm the model before capture starts

Loading Whisper lazily on the first utterance stalls the process long enough
to garble or drop the *next* utterance (observed: a clean second line came
out as "Mate gute Calling", the third never arrived). Transcribe one second
of zeros before opening the stream. Then print the readiness line.

### 4. Filter Whisper's phantoms

Whisper invents text for silence and noise. Two shapes:

- **A stock subtitle phrase as the whole utterance**: "Thank you.", "You",
  "Thanks for watching!", in Russian "Продолжение следует...". Pure silence
  produces these with *high* confidence (avg_logprob around -0.24).
- **One phrase repeated for a whole line.**

The textbook filter (`no_speech_prob > 0.6 and avg_logprob < -1.0`) does
not work with **large-v3-turbo**: measured `no_speech_prob` is 0.0 on white
noise, brown noise and silence alike. What works:

- drop segments with `compression_ratio > 2.4` (Whisper's own repetition
  threshold; a 30x repeated phrase measures about 19);
- discard an utterance that is *only* a known phantom phrase, matched on the
  whole normalised text, never as a substring.

Verify by feeding noise and silence arrays straight into your transcribe
function: they must come back empty.

### 5. Give Whisper the vocabulary

Pass the domain's proper nouns as `initial_prompt` (e.g. the agent's name
and the account names). It fixes misheard names; it can also title-case the
output, which a downstream model ignores. A rewrite prompt downstream cannot
fix a name it has never seen.

### 6. Expect the real mic to differ

- **Permission is per app.** macOS grants the microphone to the terminal app,
  not the process. Without it the stream opens and delivers *no callbacks at
  all* (not silence): a level meter that prints nothing is the tell.
- **Room noise crosses a -45 dBFS gate** on a laptop mic; raise to about -40
  in a noisy room. Phantom filtering (step 4) handles what still gets through.
- **The presenter's voice is on the mic, not the loopback.** BlackHole only
  carries what the machine plays (e.g. the far side of a meeting).
- **"Does not react" is usually latency.** End-of-utterance silence (about
  1.2 s) + transcription + the model call + whatever answers downstream.
  Measure each before tuning; a shorter silence window risks cutting a
  request in half.

## Verification

- Scripted run: ignore-lines produce no output; act-lines produce exactly the
  expected output, in order, with no extra lines.
- Noise check: white noise, brown noise and silence transcribe to empty.
- Real mic: one spoken act-line produces the output; the terminal shows the
  `heard:` line you actually said.

## Notes

- `say` voices are mechanical; that makes recognition easier than a person.
  Add a fast-rate line to keep the test honest.
- The same loopback trick feeds browser Web Speech: set Chrome's mic to
  BlackHole and play a rendered file (`say -o file.wav`) into it.
