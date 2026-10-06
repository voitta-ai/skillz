---
name: chrome-not-secure-tls-interception
description: |
  Diagnose Chrome's "Your connection to this site is not secure" on a major
  site (gmail.com, google.com, github.com) on a machine behind a corporate
  TLS-inspecting proxy (Zscaler, Netskope, Palo Alto, Blue Coat). Use when:
  (1) Chrome's site-info bubble shows the red triangle and "You should not
  enter any sensitive information on this site", (2) a CLI `openssl`/`curl`
  check of the same host looks perfectly clean and you cannot reproduce the
  browser's complaint, (3) you are about to tell someone their proxy is
  MITM-ing them. Covers the PAC-proxy blind spot in CLI checks, how to read
  the intercepted chain, and — critically — why a forged proxy certificate
  with zero SCTs is the NORMAL steady state and usually NOT the cause.
author: Claude Code
version: 1.0.0
date: 2026-08-26
---

# Chrome "not secure" behind a TLS-inspecting proxy

## Problem

Chrome flags a major HTTPS site as insecure on a corporate-managed machine.
Every CLI check of that host returns a clean, publicly-trusted certificate, so
the browser and the terminal appear to disagree.

Investigating this leads straight into a trap: you eventually find that the
corporate proxy IS forging certificates for the site, and conclude that is the
bug. **It usually isn't.** On a machine running Zscaler or similar, interception
of nearly every host is the everyday baseline — including Google properties.
Reporting it as the root cause sends the user to IT over a red herring.

## Trigger conditions

- Chrome site-info bubble: red triangle, "Your connection to this site is not
  secure. You should not enter any sensitive information on this site (for
  example, passwords or credit cards), because it could be stolen by attackers."
- `openssl s_client -connect host:443` from the same machine returns the real,
  publicly-trusted certificate with `Verify return code: 0 (ok)`.
- The machine runs a TLS-inspecting agent (Zscaler Client Connector, Netskope,
  etc.).

## Why the CLI and the browser disagree

The proxy is configured via **PAC**, not via `http_proxy`/`https_proxy`. Chrome
reads the system PAC; `openssl` and bare `curl` do not. So the CLI goes direct
and sees the real certificate while Chrome goes through the interceptor.

```bash
scutil --proxy    # macOS: look for ProxyAutoConfigURLString
```

A Zscaler install looks like:

```
ProxyAutoConfigEnable    : 1
ProxyAutoConfigURLString : http://127.0.0.1:9000/localproxy-<hash>.pac
```

Fetch the PAC and read it — a Zscaler PAC returns `DIRECT` for RFC1918/CGNAT
targets and `PROXY 127.0.0.1:9000` for everything else.

## Diagnostic procedure

### 1. Compare direct vs. proxied certificate

```bash
HOST=gmail.com

# direct — what the CLI normally sees
echo | openssl s_client -connect $HOST:443 -servername $HOST 2>/dev/null \
  | openssl x509 -noout -issuer -subject

# through the PAC proxy — what the browser sees
echo | openssl s_client -proxy 127.0.0.1:9000 -connect $HOST:443 -servername $HOST 2>/dev/null \
  | openssl x509 -noout -issuer -subject
```

A forged chain looks like `subject= /CN=gmail.com/O=Zscaler Inc.` issued by
`CN=Zscaler Intermediate Root CA (...)`. **Record this, but do not conclude
anything yet.**

### 2. Check whether the forged chain is locally trusted

```bash
# split the presented chain
echo | openssl s_client -proxy 127.0.0.1:9000 -connect $HOST:443 -servername $HOST -showcerts 2>/dev/null \
  | awk '/BEGIN CERT/,/END CERT/' > /tmp/chain.pem
awk 'BEGIN{n=0} /-----BEGIN CERTIFICATE-----/{n++} {if(n>0) print > sprintf("/tmp/c_%02d.pem", n)}' /tmp/chain.pem

ARGS=""; for f in /tmp/c_*.pem; do ARGS="$ARGS -c $f"; done
security verify-cert $ARGS -p ssl -s "$HOST"

security dump-trust-settings -d          # admin-domain roots
```

Two outcomes:

- **`certificate verification successful`** — the proxy root is a locally
  installed anchor. Chrome exempts locally-anchored chains from Certificate
  Transparency enforcement *and* from static key pinning, so the missing SCTs
  are harmless. **The interception is not your bug. Go to step 4.**
- **verification fails** — the proxy root is missing, or the chain terminates
  at an intermediate rather than the installed root. *This* is a real cause.
  Fix the trust store.

Note that `security verify-cert` reports CT separately:

```
Certificate Transparency (CT) status: not verified
Unable to find at least 2 signed certificate timestamps (SCTs) from approved logs
```

For an intercepted chain this line is **expected and benign** whenever
verification itself succeeded. Do not report it as the finding.

### 3. Rule out a stored certificate click-through

```bash
for p in ~/Library/Application\ Support/Google/Chrome/*/Preferences; do
  echo "--- $p"
  python3 -c "
import json,sys
d=json.load(open(sys.argv[1])).get('profile',{}).get('content_settings',{}).get('exceptions',{}).get('ssl_cert_decisions',{})
print(json.dumps(d,indent=1) if d else '(none)')" "$p"
done
```

An entry for the host means someone clicked through an interstitial. Absent for
HSTS-preloaded hosts anyway — Chrome offers no "proceed anyway" for those, so a
preloaded host in a dangerous state was never click-through.

Confirm preload status:

```bash
curl -s "https://hstspreload.org/api/v2/status?domain=$HOST"
```

### 4. When trust checks out, suspect transient local state

If the chain verifies, no click-through is stored, and the CT warning is the
only anomaly, the browser's dangerous state is **local and transient** — a
half-initialized proxy agent, a stale per-tab security state, a tunnel that
came up before the trust store settled.

Try, in order:

1. Hard-reload the tab / reopen it.
2. Restart the TLS-inspection agent.
3. Reboot.

Escalate to IT **only** when step 2 shows the chain genuinely failing to
verify in steady state. That is the one case where an SSL-inspection bypass or
a trust-store fix is warranted.

## Verification

Re-run step 1 and step 2 after the state clears. If the forged certificate is
*still* present but the browser is now content, the interception was never the
cause — confirming the diagnosis in step 4. That asymmetry is the whole point
of this skill.

## Notes

- **`lsof` on the proxy port proves nothing without `sudo`.** The agent runs as
  root; `lsof -nP -iTCP:9000 -sTCP:LISTEN` prints nothing as a normal user even
  while the port is listening. Absence is not evidence — `curl` the PAC URL
  instead.
- **Do not enumerate Chrome tabs via AppleScript.** `osascript -e 'tell
  application "Google Chrome" ...'` blocks on a macOS TCC automation consent
  prompt that never surfaces in a headless context; it hangs until timeout.
  Read a copy of the profile's `History` SQLite DB instead:

  ```bash
  cp ~/Library/Application\ Support/Google/Chrome/Profile\ 1/History /tmp/h.db
  sqlite3 /tmp/h.db "select datetime(last_visit_time/1000000-11644473600,'unixepoch','localtime'), url \
    from urls where url like '%$HOST%' order by last_visit_time desc limit 5;"
  ```

- The proxy genuinely does decrypt the traffic. That is a real privacy property
  worth stating plainly to the user — it is just not a *malfunction*, and it is
  not what the browser warning is about.
- Chrome enterprise policy `CertificateTransparencyEnforcementDisabledForCas`
  exists for the case where a formerly-public CA must stay trusted without CT.
  It is not needed for an ordinary locally-installed inspection root.

## References

- [Chromium: Certificate Transparency](https://chromium.googlesource.com/chromium/src/+/lkgr/net/docs/certificate-transparency.md)
- [Chrome Root Store FAQ](https://chromium.googlesource.com/chromium/src/+/main/net/data/ssl/chrome_root_store/faq.md)
- [Zscaler: Certificate Pinning and SSL Inspection](https://help.zscaler.com/legacy-zia/certificate-pinning-and-ssl-inspection)
- [Chrome Enterprise: CertificateTransparencyEnforcementDisabledForCas](https://chromeenterprise.google/policies/certificate-transparency-enforcement-disabled-for-cas/)
