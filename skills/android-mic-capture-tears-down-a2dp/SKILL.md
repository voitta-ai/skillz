---
name: android-mic-capture-tears-down-a2dp
description: |
  Find and fix an Android app whose microphone use kills Bluetooth audio in a
  car or on a speaker. Use when: (1) music or spoken audio stops seconds after
  connecting, and the head unit keeps reconnecting; (2) a car that used to
  auto-connect appears to have "unpaired itself" after an app that listens
  shipped; (3) an app does wake-word, dictation, continuous SpeechRecognizer,
  AudioRecord or VoIP capture while audio plays over Bluetooth; (4) you need to
  prove which app caused it, from the device, after the fact. Covers reading
  the profile-state timeline out of dumpsys bluetooth_manager, correlating it
  with appops microphone timestamps, and pinning capture to the built-in
  microphone with setCommunicationDevice so the remote device is only ever
  asked to play.
author: Claude Code
version: 1.0.0
date: 2026-09-17
source: https://github.com/voitta-ai/skillz
source_file: skills/android-mic-capture-tears-down-a2dp/SKILL.md
---

# Android microphone capture tears down A2DP

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/android-mic-capture-tears-down-a2dp/SKILL.md`).

## Problem

An app records audio while the phone is playing over Bluetooth. Android
answers the capture request by routing input to the *remote* microphone, which
means opening the hands-free profile (HFP, carrying a SCO link). Many car head
units, especially pre-2020 ones, will not keep the music profile (A2DP) alive
next to an active SCO link, so the audio stream is torn down within seconds and
the two profiles then fight: A2DP retries, fails, and the device looks broken.

It presents as a Bluetooth fault rather than an app fault, and the pairing is
still intact throughout, so the obvious first moves (forget the device, re-pair,
reboot) appear to help at random and teach you nothing.

## Context / Trigger conditions

- Audio plays over a car or speaker for a few seconds, then stops; the head
  unit reconnects repeatedly.
- A device that reliably auto-connected stops doing so, and the change lines up
  with shipping a feature that listens: a wake word, dictation, continuous
  `SpeechRecognizer`, `AudioRecord`, or any `VOICE_RECOGNITION` /
  `VOICE_COMMUNICATION` capture.
- Symptoms appear only in the car, never on the phone speaker or wired.
- The remote device is still bonded, which is why "it unpaired itself" is a
  false lead.

## Solution

### 1. Read the profile timeline off the device

```bash
adb shell dumpsys bluetooth_manager | grep -iE '<mac-fragment>|connection state changed|Active Device'
```

The signature is A2DP connecting, the headset profile becoming the active
device, and A2DP dying moments later:

```
22:05:19.826 A2DP connection state changed: <mac> STATE_CONNECTING -> STATE_CONNECTED
22:05:20.208 Active Device Changed: <mac> for profile: A2DP
22:05:20.648 Active Device Changed: <mac> for profile: HEADSET
22:05:21.786 A2DP connection state changed: <mac> STATE_CONNECTED -> STATE_DISCONNECTING
22:05:25.962 A2DP connection state changed: <mac> STATE_CONNECTING -> STATE_DISCONNECTED
```

Two seconds between "headset becomes active" and "music stream gone" is the
tell. This log survives reboots of the app and is timestamped, so it works
after the fact — you do not have to reproduce it live in a car.

### 2. Name the app that asked for the microphone

`appops` records the last microphone access per package, as an age rather than
a clock time:

```bash
adb shell cmd appops get <package> RECORD_AUDIO
# RECORD_AUDIO: allow; time=+14h56m40s528ms ago; ...
```

Convert the age to a wall-clock time and compare it with the timeline above. A
match in the same minute is your culprit. To sweep rather than guess a package:

```bash
adb shell cmd appops query-op RECORD_AUDIO allow
```

Also confirm nothing holds the microphone *now*, so you are not chasing a live
capture that is simply idle at the moment:

```bash
adb shell dumpsys media.audio_flinger | grep -iE 'input|record'
```

### 3. Keep capture on the phone's own microphone

Pin the communication device to the built-in microphone for as long as you are
listening. The remote device is then only ever asked to play, no SCO link is
opened, and A2DP is left alone:

```kotlin
private val audio = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager

// Before starting recognition or recording:
if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
    audio.availableCommunicationDevices
        .firstOrNull { it.type == AudioDeviceInfo.TYPE_BUILTIN_MIC }
        ?.let { audio.setCommunicationDevice(it) }
}

// When you stop listening:
if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
    audio.clearCommunicationDevice()
}
```

`setCommunicationDevice` returns a boolean; log it, because a refusal is
silent otherwise. On API 30 and below the equivalent is avoiding
`startBluetoothSco()` and setting `AudioManager.MODE_NORMAL`, but the routing
is not guaranteed the same way.

Clear the device when listening stops. Leaving it pinned keeps the input route
overridden for the rest of the process's life, which will surprise the next
feature that wants the headset microphone deliberately.

## Verification

1. Play audio over the Bluetooth device.
2. Turn listening on.
3. The audio must keep playing. Re-read the timeline: there should be no
   `Active Device Changed: … for profile: HEADSET` and no A2DP disconnect.

```bash
adb shell dumpsys bluetooth_manager | grep -iE 'connection state changed|Active Device' | tail -20
```

## Notes

- **Echo is the trade-off.** The phone's microphone hears whatever the car
  speakers are playing, so recognition has to cope with the recording talking
  over the speaker. Ducking or pausing playback while listening is the usual
  answer; using the remote microphone instead is not, on affected hardware.
- **Phone calls still work.** Pinning only affects capture the app initiates.
  A call routes to the car normally, because the telephony stack manages its
  own device selection.
- Newer head units often survive simultaneous SCO and A2DP, which is why this
  can pass every test on a modern car and fail on a 2019 one. Test on the
  oldest device you care about.
- The same failure shape appears with any capture source, not just speech
  recognition: VoIP, voice memos, and level meters all request an input route.
- Nothing here needs a rooted device or a bug report; `dumpsys` and `appops`
  are enough, which makes this a viable post-mortem when the only evidence is
  "it broke in the car yesterday evening".

## References

- [AudioManager.setCommunicationDevice](https://developer.android.com/reference/android/media/AudioManager#setCommunicationDevice(android.media.AudioDeviceInfo))
- [AudioDeviceInfo.TYPE_BUILTIN_MIC](https://developer.android.com/reference/android/media/AudioDeviceInfo#TYPE_BUILTIN_MIC)
- [Bluetooth profiles on Android: A2DP and HFP](https://source.android.com/docs/core/connect/bluetooth)
