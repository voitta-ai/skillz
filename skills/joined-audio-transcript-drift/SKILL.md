---
name: joined-audio-transcript-drift
description: |
  Keep timestamps aligned when joining many audio files into one. Use when:
  (1) subtitles, transcript segments, chapters or bookmarks drift later and
  later through a concatenated file; (2) the joined file is seconds longer than
  the sum of its parts; (3) ffmpeg's concat demuxer prints "Application
  provided invalid, non monotonically increasing dts to muxer"; (4) you are
  stitching TTS chunks, per-chapter downloads or recorded segments and need
  measured durations to add up. Explains why a lossless copy keeps each piece's
  gapless padding, why frame counts still do not match, when re-encoding once
  is the right trade, and how to verify drift rather than assume it.
author: Claude Code
version: 1.0.0
date: 2026-09-17
source: https://github.com/voitta-ai/skillz
source_file: skills/joined-audio-transcript-drift/SKILL.md
---

# Joined audio drifts away from its transcript

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/joined-audio-transcript-drift/SKILL.md`).

## Problem

You join many audio pieces into one file and build a transcript, a chapter
list or a set of bookmarks by adding up each piece's duration. Early
timestamps look right. Later ones point at the wrong place, by more the
further in you go.

The cause is that a compressed piece is longer than the audio it represents.
An encoder pads the start and end of every file, and records in a header how
much to trim. `ffprobe` reports the *trimmed* duration, which is what a player
would give you, but `concat -c copy` copies whole frames and keeps the padding
of every piece. Each join therefore adds a few tens of milliseconds that your
arithmetic never sees, and they accumulate.

Measured on 181 pieces joined into one 164-minute MP3: the joined file ran
**9.1 seconds longer** than the sum of the pieces, about 50 ms per join.

## Context / Trigger conditions

- Timestamps are correct at the start of a joined file and progressively later
  toward the end.
- The joined file's duration is longer than the sum of the parts' durations.
- ffmpeg prints, during a copy-mode concat:
  `Application provided invalid, non monotonically increasing dts to muxer in stream 0`
- You are stitching synthesized speech chunks, per-chapter or per-track
  downloads, or recorded segments, and something downstream needs to seek by
  time: captions, bookmarks, chapter marks, alignment.

## Solution

### Do not trust frame counts either

The obvious repair is to compute each piece's contribution from its frame
count rather than its trimmed duration:

```bash
ffprobe -v error -select_streams a:0 -count_frames \
  -show_entries stream=nb_read_frames,sample_rate -of json piece.mp3
```

For MPEG-2 Layer III (sample rates 16/22.05/24 kHz) a frame is 576 samples;
for MPEG-1 (32/44.1/48 kHz) it is 1152. This gets closer but still does not
match: each input's header frame (Xing/Info/LAME) is copied through as well,
so the joined file carries roughly one extra frame per piece. On the same
29-minute test the frame arithmetic was still 1.3 seconds out.

### Encode once, and the arithmetic holds

Decoding everything and encoding the result once produces a single contiguous
stream whose length is the sum of the decoded pieces:

```bash
ffmpeg -nostdin -loglevel error -y -f concat -safe 0 -i list.txt \
  -c:a libmp3lame -b:a 64k -ar 24000 -ac 1 -write_xing 0 joined.mp3
```

On the same material this brought 2.51 seconds of drift down to **0.06
seconds**, and took 6 seconds for a 29-minute file. `-write_xing 0` keeps the
output from gaining a header frame of its own.

The cost is one extra lossy generation. For speech at a low bitrate that is a
fair trade for timestamps that land; for music, or where the source is already
poor, consider the alternatives below.

### Alternatives when re-encoding is unacceptable

- **Use a format that concatenates exactly.** Uncompressed WAV or FLAC has no
  encoder padding: join those, and encode once at the end if you need to.
- **Encode the whole thing in one pass from the start.** If you control
  production, synthesize or record into one stream rather than joining later.
- **Splice frames yourself**, stripping ID3 and header frames and counting
  frames as you go. Exact and lossless, but you own an MP3 parser.

## Verification

Compare the joined file against the sum of its parts, and report the
difference rather than assuming it is zero:

```bash
sum=$(for f in piece*.mp3; do
  ffprobe -v error -show_entries format=duration -of csv=p=0 "$f"
done | paste -sd+ - | bc)
joined=$(ffprobe -v error -show_entries format=duration -of csv=p=0 joined.mp3)
echo "sum=$sum joined=$joined drift=$(echo "$joined - $sum" | bc)"
```

Keep that check in the build and print the drift every time: it is one line,
and it turns a silent slide into a number you can watch.

## Example

Building one recording per module out of 181 pieces, half downloaded and half
synthesized, with a transcript segment per piece:

| Approach | Drift over 164 minutes |
|---|---|
| `-c copy` (lossless join) | +9.10 s |
| frame-count arithmetic | ~1.3 s on a 29-minute file |
| single re-encode | +0.05 s |

The bookmark windows in that project reached 45 seconds back, so nine seconds
of drift meant a mark could surface the wrong passage entirely.

## Notes

- The same padding exists in AAC/M4A; the numbers differ, the shape does not.
- `ffprobe`'s duration is the player's view, which is why it disagrees with
  what a copy produces. Neither is wrong; they answer different questions.
- Concatenating pieces with different sample rates, channel counts or bitrates
  forces a re-encode anyway. Normalizing each piece to one format as you
  produce it makes the join cheap and the decision easy.
- If a downstream consumer only ever seeks near the beginning, drift can be
  invisible in testing. Test the end of the longest output.

## References

- [ffmpeg concat demuxer](https://ffmpeg.org/ffmpeg-formats.html#concat)
- [LAME gapless playback metadata](https://lame.sourceforge.io/tech-FAQ.txt)
- [Xing/Info header frame](https://www.codeproject.com/Articles/8295/MPEG-Audio-Frame-Header)
