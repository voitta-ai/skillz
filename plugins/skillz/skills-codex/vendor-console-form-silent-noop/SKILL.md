---
name: vendor-console-form-silent-noop
description: |
  Driving a vendor's web console (buy, provision, submit) through browser
  automation and the confirm button does nothing at all - no error, no toast,
  no navigation, and a required consent checkbox clears itself every time. Use
  when: (1) a submit button appears to work but the dialog just stays open,
  (2) a required checkbox visually ticks and then un-ticks on submit, (3) your
  click or a form-input/value-set on a checkbox "worked" per the tool result
  yet the app behaves as if it is unchecked, (4) you are about to retry the
  same click a fourth time, (5) you need to know whether the request is even
  leaving the browser before you blame the UI, (6) an automation run silently
  failed N times and you cannot tell whether the vendor rejected it or the
  page never submitted. Two independent causes, each masquerading as the
  other: a framework-controlled input that ignores synthetic clicks, and a
  server error the console renders nowhere. Covers telling them apart in one
  step, the real-keypress fix, and reading the swallowed response body.
author: Claude Code
version: 1.0.0
date: 2026-09-21
source: https://github.com/voitta-ai/skillz
source_file: skills/vendor-console-form-silent-noop/SKILL.md
---

# A vendor console's form that silently does nothing

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/vendor-console-form-silent-noop/SKILL.md`).

## Problem

You are automating a provisioning flow in somebody else's web console - buy a
phone number, create a resource, accept terms and submit. You click the confirm
button. Nothing happens. The modal stays open. There is no error text, no
toast, no spinner, no navigation. The required "I agree to..." checkbox, which
you just ticked and saw tick, is unchecked again.

The natural read is "my click missed" or "the checkbox is broken", so the
natural response is to click again. That is the trap: on the run that produced
this skill, five identical attempts went out before anything was learned, and
each one was a real request the vendor rejected.

There are **two independent causes** and each one imitates the other:

1. **The control is framework-managed** (React/Vue/Angular controlled input).
   A synthetic click flips the DOM's `checked` property but never reaches the
   framework's state. Submit validates against the state, which is still
   `false`, so it no-ops and re-renders - which *resets the visible checkbox*.
2. **The submit really did fire and the server rejected it.** The console
   renders the error nowhere, and re-renders the form, which *also* resets the
   visible checkbox.

Same symptom, opposite diagnosis. Guessing wastes attempts; on a purchasing
flow, attempts can cost money or consume inventory.

## Context / Trigger conditions

- A confirm/submit button in a third-party console does nothing, repeatedly.
- A required consent checkbox reverts to unchecked after every submit.
- Your automation tool reports the click or the value-set as successful.
- Console errors, if any, are opaque minified stack traces with no message:

  ```
  [ERROR] (https://console.example.com/16265.c827ecf4.js:0:188455)
  Error
      at https://console.example.com/14496.44781a42.js:895:160459
      at Generator.throw (<anonymous>)
  ```

  One such line per attempt is itself a signal: the code path *is* running and
  throwing, which points at cause 2.

## Solution

### Step 0 - decide which cause you have, before clicking again

Do this first; it takes one call and it is read-only.

```js
// In the page, before the next submit attempt.
const cb = document.querySelector('input[name="<the checkbox name>"]');
const btn = [...document.querySelectorAll('button')]
              .find(b => /^Confirm|^Buy|^Submit/.test(b.textContent.trim()));
({ checked: cb && cb.checked, disabled: btn && btn.disabled });
```

Then arm a fetch interceptor so the next attempt cannot fail invisibly:

```js
if (!window.__origFetch) {
  window.__origFetch = window.fetch;
  window.__log = [];
  window.fetch = async function (...args) {
    const res = await window.__origFetch.apply(this, args);
    try {
      const u = typeof args[0] === 'string' ? args[0] : args[0].url;
      if (u && u.includes('<the resource path>')) {
        window.__log.push({
          url: u,
          status: res.status,
          body: (await res.clone().text()).slice(0, 1500),
        });
      }
    } catch (e) {}
    return res;
  };
}
'patched';
```

Submit once more, then read `window.__log`.

- **An entry appears with a 4xx/5xx body** -> cause 2. The form works; the
  vendor said no. The body usually carries the real message and a vendor error
  code. Act on that, do not retry.
- **No entry at all** -> cause 1. The request never left the page, so the
  submit handler bailed on its own validation. Go to the keypress fix.

A cheaper first probe, if your automation exposes network logging: look for an
`OPTIONS` preflight to the resource endpoint. A preflight means the POST was
attempted, which already distinguishes the two causes.

### Step 1 (cause 1) - check the box with a real key event

A synthetic click and a programmatic value-set both fail here, for the same
reason: neither produces the trusted event the framework listens for. What
works is focusing the input and sending a genuine `Space` keypress through the
automation layer's keyboard channel.

```js
// 1. focus it from the page
document.querySelector('input[name="<the checkbox name>"]').focus();
```

```
2. send a real keypress via the automation tool, not via JS:
     key: "space"
3. verify:  document.querySelector('input[name="..."]').checked  -> true
4. click the submit button
```

Verify in that order. If the checkbox reads `true` and submit still no-ops, you
are actually in cause 2 and the interceptor from step 0 will now show why.

Note the ordering trap: if you click the checkbox *and then* press Space, you
toggle it twice and end up back where you started.

### Step 2 (cause 2) - read the vendor error and adapt

The body is the whole answer. A worked example, from buying a phone number:

```json
{"message":{"statusCode":400,"error":"Bad Request",
 "message":"+1XXXXXXXXXX is not available.",
 "data":{"vendorErrorCode":21422}},"status":400}
```

The item had been taken by someone else between the search and the purchase -
inventory lists in provisioning consoles go stale in minutes. The fix was to
refresh the list and take a different item, which then succeeded first try
(HTTP 201). No amount of clicking would ever have worked.

### Step 3 - before retrying anything, check whether it half-succeeded

Silent failure cuts both ways: you may also have silently *succeeded*, more
than once. Before another attempt, list the resource:

```js
const r = await fetch('<the list endpoint>', { credentials: 'include' });
({ status: r.status, body: (await r.text()).slice(0, 800) });
```

On the run behind this skill, five failed attempts had created nothing - but
that was worth two seconds to establish rather than assume, because the failure
mode gives you no other way to know.

## Verification

- `window.__log` holds an entry with a 2xx status, or
- the resource now appears in the list endpoint from step 3, or
- the modal closes and the console navigates.

Do not treat "the checkbox stayed checked" as success. It is a rendering
detail, not an outcome.

## Example

Condensed from the session this came from:

1. Click Buy on an item from the search results -> modal opens.
2. Tick the terms checkbox (synthetic click) -> it visibly ticks.
3. Click the confirm button -> nothing; checkbox unchecked.
4. Repeat 2-3 four more times, each time reading as "the checkbox is broken".
5. Read console errors: five identical opaque `Error` lines, one per attempt
   -> something *is* running and throwing.
6. Arm the fetch patch, attempt once more, read `window.__log`:
   `400 ... "is not available" ... 21422`.
7. Confirm nothing was created: list endpoint returns an empty array.
8. Refresh the inventory list, pick a different item, focus the checkbox, send
   a real `Space`, click confirm -> `201`.

Both causes were present at once, which is why neither was visible alone: the
checkbox genuinely was not registering, *and* the chosen item was genuinely
unavailable.

## Notes

- **Cost discipline.** On a provisioning console a retry is not free - it can
  consume inventory, spend credit, or create a record. Two read-only calls
  (the interceptor and the list endpoint) are cheaper than a third blind
  attempt. Budget them before, not after.
- **`form_input`-style tool helpers do not rescue cause 1.** Setting the value
  through the accessibility layer has the same problem as a synthetic click:
  no trusted event, no framework state change.
- **Tab-then-Enter is a trap** for reaching the submit button. Consent rows
  usually put a "terms and conditions" link immediately after the checkbox, so
  Tab lands on the link and Enter opens it in a new tab.
- **Clean up the patch.** `window.fetch` stays patched for the life of the
  page. Restore it (`window.fetch = window.__origFetch`) or close the tab when
  done, so later reads are not silently logged.
- **Distinguish from a blocked request.** If nothing reaches the network *and*
  the page shows no error, also consider that the automation click landed on a
  transparent overlay or an animating modal. Screenshot between the focus and
  the submit; a modal caught mid-animation is a real cause of missed clicks and
  looks like neither of the two above.

## Related

- `spa-request-capture-and-block` - the fuller version of the interception
  half: patching `XMLHttpRequest` as well as `fetch`, zone.js apps, and
  blocking a request rather than just observing it. Reach for it when the app
  is Angular, when the capture "did not fire", or when the click itself must
  not be allowed through.
- `client-rendered-dashboard-data-blob` - when the problem is reading data a
  console renders client-side, rather than submitting to it.
