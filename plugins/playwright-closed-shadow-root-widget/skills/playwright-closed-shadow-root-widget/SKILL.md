---
name: playwright-closed-shadow-root-widget
description: |
  Drive an injected widget (a bookmarklet, browser-extension panel, or embeddable chat
  widget) that mounts its UI inside a CLOSED shadow root, from Playwright or Playwright
  MCP, in an end-to-end check. Use when: (1) the widget is visibly rendered in a
  screenshot, but `document.querySelectorAll('textarea, button')` finds nothing;
  (2) the host element exists but `host.shadowRoot` is `null`; (3) Playwright selectors
  and `playwright_fill`/`playwright_click` time out on elements you can see; (4) you
  need to type into a React-controlled textarea inside that root and actually trigger
  send. Fix: patch `Element.prototype.attachShadow` to force `mode: 'open'` BEFORE the
  widget's code runs, then reach the UI through `host.shadowRoot`, and set React
  inputs with the native value setter plus an `input` event.
author: Claude Code
version: 1.0.0
date: 2026-10-08
---

# Driving a widget in a closed shadow root

## Problem

Widgets injected into other people's pages often isolate themselves with
`attachShadow({mode: 'closed'})`. A closed root is invisible to page scripts:
`host.shadowRoot` returns `null`, and neither `document.querySelector` nor Playwright's
selector engine can reach inside it. Playwright's CSS engine pierces open shadow roots
only. You get a correct-looking screenshot and no way to type into the widget or click
its buttons, so an end-to-end check of the widget stalls at "it rendered".

## Context / Trigger Conditions

- The widget is visible, but `[...document.querySelectorAll('*')].filter(e => e.shadowRoot)`
  is empty. A closed root does not show up in that filter.
- There is a host element (often the last child of `<html>` or `<body>`, with an id
  like `<app>-host`), and its `shadowRoot` is `null`.
- No iframe is involved. If there is one, use frame locators instead; this skill does
  not apply.

## Solution

1. **Patch before the widget mounts.** `attachShadow` is called once, when the widget
   boots. The patch has to be in place in the same page realm before that call.
   - **Widget injected by your test** (a bookmarklet, or an `eval` of the widget
     bundle): run the patch in the same `evaluate` call, ahead of the injection.
   - **Widget loaded by the page itself:** use `page.addInitScript(...)` so the patch
     runs before any page script.
   - **Widget already mounted:** reload the page first. Patching afterwards does
     nothing.

   ```js
   const orig = Element.prototype.attachShadow;
   Element.prototype.attachShadow = function (opts) {
     return orig.call(this, { ...opts, mode: 'open' });
   };
   // ...then inject / boot the widget here
   ```

2. **Find the UI through the host.**

   ```js
   const sr = document.getElementById('<app>-host').shadowRoot;   // now non-null
   sr.querySelectorAll('textarea, button');
   ```

   Once the root is open, Playwright's own selectors pierce it as well
   (`page.locator('textarea')`), so `fill`/`click` work again.

3. **Type into a React-controlled input.** Assigning `ta.value = '...'` does not
   update React's state, so Send stays disabled or sends an empty message. Use the
   native setter and dispatch `input`:

   ```js
   const ta = sr.querySelector('textarea');
   const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
   set.call(ta, 'your message');
   ta.dispatchEvent(new Event('input', { bubbles: true }));
   ```

   For an `<input>`, use `HTMLInputElement.prototype` instead.

4. **Click by accessible name, not by position.** Find the button by its label:

   ```js
   [...sr.querySelectorAll('button')]
     .find(b => (b.getAttribute('aria-label') || b.title) === 'Send').click();
   ```

5. **Read the result.** Wait for the turn to finish, then read `sr.textContent`, or
   query the message nodes inside `sr`. Tail the backend log at the same time, so a
   server-side error is not mistaken for a slow reply.

## Verification

- `document.getElementById('<app>-host').shadowRoot` is non-null after the boot.
- The textarea and its buttons are listed from `sr.querySelectorAll`.
- After the click, your message appears in the widget's transcript, followed by the
  response. If the widget renders tool steps, they show their input and output.

## Example

This was used to verify, end to end, a refactor of a bookmarklet assistant's agent
loop. Steps:

1. Run the PR branch's backend on a spare loopback port.
2. Open `https://example.com` in Playwright MCP.
3. In one `playwright_evaluate`:
   - apply the `attachShadow` patch;
   - run the bookmarklet's bootstrap (it opens a relay popup and `eval`s the widget
     bundle into the page);
   - wait about 10 s.
4. In a second `playwright_evaluate`, fill the composer with "Use the get_page_title
   tool to read this page title, then reply with just the title." through the native
   setter, and click Send.
5. After about 45 s, `sr.textContent` contained the tool step (input `{}`, output
   `{"title": "Example Domain"}`) and the reply "Example Domain".

Before the patch, the same page showed the widget in a screenshot, but there was no
shadow host with a `shadowRoot`, and no textarea or button could be found.

## Notes

- **Test-only.** The patch changes how the page behaves: page scripts can now see
  into every shadow root created after it. Use it in a disposable browser context,
  never in a user's real profile, and never in product code.
- **Some widgets refuse an open root.** A widget may check `this.shadowRoot` after
  attaching, or keep a private reference, and still work. Others hard-fail when the
  root is open; they are rare. Then fall back to keyboard-only driving: focus the
  host, `Tab` into the root, and type with `page.keyboard`.
- **Close the browser afterwards.** A widget that opens a relay or bridge popup keeps
  that window open. Close the browser so the next test starts clean.
- **Not iframes.** For a widget in a cross-origin iframe, use
  `page.frameLocator(...)`. The problem there is origin, not shadow-root mode.

## References

- MDN, `Element.attachShadow()`: the `mode` option, and `shadowRoot` returning
  `null` for closed roots. https://developer.mozilla.org/en-US/docs/Web/API/Element/attachShadow
- Playwright, Locators: selectors pierce open Shadow DOM by default and do not
  pierce closed roots. https://playwright.dev/docs/locators#locate-in-shadow-dom
- Playwright, `page.addInitScript`: runs a script before any page script, to patch
  before the widget mounts. https://playwright.dev/docs/api/class-page#page-add-init-script
