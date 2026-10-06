---
name: reverse-engineer-react-native-hermes-app
description: |
  Reverse-engineer an Android app whose logic is a React Native Hermes bytecode
  bundle, off a stock non-rooted device, and know in advance which capture
  layers actually work without root. Use when: (1) an APK's `assets/index.android.bundle`
  is "Hermes JavaScript bytecode" and classes*.dex is only RN/SDK glue,
  (2) you need the app's real endpoints/flows but there is no source,
  (3) you plan to intercept the app's HTTPS and want to know if it's even possible
  without root, (4) you need to observe BLE traffic to a peripheral without root,
  (5) a proxy you set broke every app's networking (incl. the Gmail outbox), not
  just the target. Covers hermes-dec on unsupported bytecode versions, string-table
  flow tracing, the user-CA trust wall, and no-root BLE/HTTP capture routes.
author: Claude Code
version: 1.0.0
date: 2026-09-21
---

# Reverse-engineering a React Native / Hermes Android app (stock, no root)

## Problem
The app is React Native, so `jadx`/smali gives you only the RN runtime and SDK
glue — the actual business logic is compiled JavaScript in a Hermes bytecode
bundle. And on a modern stock phone, the obvious next step (proxy the traffic
with mitmproxy) silently fails for reasons that have nothing to do with the app.

## Context / Trigger Conditions
- `file assets/index.android.bundle` -> `Hermes JavaScript bytecode, version NN`.
- You pulled a **split** APK: `base.apk` + `split_config.*` (the bundle is in base).
- HTTPS interception via a user-installed CA fails with, for *every* app:
  `Client TLS handshake failed. The client does not trust the proxy's certificate`.
- You need BLE traffic to a peripheral but have no root.

## Solution

### 1. Pull and unpack (bundle lives in base)
```bash
adb shell pm path <pkg>                 # lists base.apk + split_config.*
adb pull <path>/base.apk .
unzip -o base.apk -d extracted
file extracted/assets/index.android.bundle    # confirm Hermes + version
```

### 2. Recover logic from the Hermes bundle
- **Strings first** — endpoints, SDK names, feature flags recover directly:
  `strings -n 5 index.android.bundle | grep -oiE 'https?://[a-z0-9._/-]+' | sort -u`
  (the Hermes string table packs identifiers contiguously, so grep for known
  fragments like `api/`, function-name substrings; expect run-together tails).
- **Decompile with P1sec hermes-dec** (`github.com/P1sec/hermes-dec`). It supports
  many versions and, crucially, still emits usable output on **unsupported/newer
  bytecode versions** — it prints `Bytecode version NN ... is not formally
  supported` and proceeds. Run modules directly, no pip needed:
  ```bash
  git clone --depth 1 https://github.com/P1sec/hermes-dec.git
  export PYTHONPATH=hermes-dec/src
  python3 hermes-dec/src/hermes_dec/disassembly/hbc_disassembler.py bundle disasm.hasm
  python3 hermes-dec/src/hermes_dec/decompilation/hbc_decompiler.py bundle decomp.js
  ```
  `decomp.js` is register-machine pseudo-JS (`switch(ip)` state machines), not
  clean JS — but object literals, string loads, and `AxiosApi.post(url, {...})`
  bodies are all readable. Trace a flow by grepping a function name in `decomp.js`,
  then read the literal it builds; cross-check operands in `disasm.hasm`
  (`GetById ... # String: 'name'`).

### 3. Decode the manifest (perms, deeplinks, exported components)
The binary AndroidManifest is in the APK, not the bare dex — decode from the APK:
`jadx -d out --no-src base.apk` then read `out/resources/AndroidManifest.xml`.

### 4. Pick a capture layer that works WITHOUT root
- **HTTP/HTTPS — usually NOT possible on a stock phone.** Since Android 7, apps
  targeting API >= 24 do **not** trust user-installed CA certs unless their own
  network-security-config opts in (modern apps don't). So mitmproxy-via-user-CA
  fails at the TLS handshake — and it fails for **every** app, which is the tell
  it's the user-CA wall, not app-specific pinning. You never even reach any
  `okhttp3/CertificatePinner` that ships in the dex. Real decryption needs a
  **rooted** device (system-store CA or Frida-unpin), or PCAPdroid's mitm addon
  (same user-CA limitation). Do NOT re-sign the app to add a CA-trusting config:
  it breaks Play Integrity and is the wrong tool for "just observe".
- **BLE — YES, without root, via the HCI snoop log:**
  1. Developer options > "Enable Bluetooth HCI snoop log" = Enabled; toggle
     Bluetooth off/on to start logging.
  2. Reproduce the action.
  3. `adb bugreport out.zip` (no root needed) bundles
     `FS/data/misc/bluetooth/logs/btsnoop_hci.log`; extract it and open in
     Wireshark/`tshark` (btsnoop encap decodes natively). Filter ATT writes:
     `tshark -r btsnoop.log -Y 'btatt.opcode.method in {0x12 0x1b 0x52}' -T fields
      -e btatt.handle -e btatt.value`.
     `/data/misc/bluetooth/logs/` itself is root-only; the bugreport is the way in.
- **Screen/taps/logs — YES:** `screenrecord` + Dev-options "Show taps" for video,
  `getevent -lt` for timestamped touches, `logcat --pid=$(adb shell pidof <pkg>)`
  for the app's own logs (works on a non-debuggable build; `run-as` does not).

## Verification
- hermes-dec ran if `decomp.js`/`disasm.hasm` are non-empty despite the version
  warning.
- The user-CA wall is confirmed (not app pinning) when the TLS handshake failures
  in the proxy log name *unrelated* hosts too (google, linkedin, ...), not only
  the target.
- BLE capture worked if the bugreport contains a non-empty `btsnoop_hci.log`
  (empty -> the Dev-options toggle + BT restart didn't take).

## Notes
- **A global proxy blackholes everything.** `adb shell settings put global
  http_proxy <ip>:<port>` routes *all* apps through the proxy; if the listener
  dies or TLS fails, every app loses networking and queued sends (e.g. the Gmail
  **outbox**) stall. Always tear down: `adb shell settings delete global http_proxy`
  and verify the phone reaches the net again. A phone that "lost wifi" after an
  intercept session is almost always a left-behind proxy setting.
- Hermes bytecode is **decompilable but not reassemblable** by hermes-dec — you
  can read logic but not patch-and-repack the bundle through it. Behavior changes
  need Frida (runtime, needs root/gadget) or recompiling modified JS with a
  matching `hermesc`. Re-signing the APK also fights Play Integrity.
- Many RN apps ship both `expo-updates` and `CodePush`: the **running** JS bundle
  may be a newer OTA download in app storage, differing from the APK's bundle.
  Static analysis is of the shipped bundle; live captures reflect whatever's running.

## References
- P1sec hermes-dec: https://github.com/P1sec/hermes-dec
- Android network security config / user CA trust (API 24+):
  https://developer.android.com/privacy-and-security/security-config
- Bluetooth HCI snoop log via bugreport: standard AOSP Developer Options behavior.
