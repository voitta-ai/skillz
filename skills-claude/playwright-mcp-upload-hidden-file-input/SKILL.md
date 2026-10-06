---
name: playwright-mcp-upload-hidden-file-input
description: |
  Upload a file via Playwright MCP when the file input is hidden. Use when:
  (1) mcp__playwright__playwright_upload_file times out with
  "page.waitForSelector: Timeout ... exceeded ... locator resolved to hidden
  <input type=file>", (2) the page has a styled "Choose files" / drag-drop
  button backed by an <input type="file" class="hidden"> or display:none
  (the default pattern in shadcn/ui, Radix, Headless UI, MUI, most React
  upload components), (3) any Playwright-MCP browser flow needs to attach a
  file and the input isn't visible. Workaround: unhide+tag the input via
  playwright_evaluate, then upload by id; verify via the resulting CDN/S3 URL.
author: Claude Code
version: 1.0.0
date: 2026-06-15
---

# Playwright MCP: upload to a hidden file input

## Problem
`mcp__playwright__playwright_upload_file` waits for the target `<input type="file">`
to be **visible** and times out when it is hidden. Almost every modern web UI hides
the real input and shows a styled "Choose files" button or drag-drop zone instead, so
this is the common case, not the edge case. Plain Playwright `setInputFiles` works on
hidden inputs; the MCP wrapper does not.

## Context / Trigger Conditions
- Tool error like:
  ```
  Operation failed: page.waitForSelector: Timeout 30000ms exceeded.
    - waiting for locator('input[type=file]...') to be visible
      locator resolved to hidden <input type="file" class="hidden" accept="image/*"/>
  ```
- DOM has `<input type="file" class="hidden">` or `style="display:none"` behind a
  button/label (shadcn/ui, Radix, Headless UI, MUI, Tailwind `sr-only`/`hidden`).
- A page exposes several file inputs (photos vs. video vs. PDF) — you must pick the
  right one by its `accept` attribute.

## Solution
1. **Unhide and tag the right input** with `playwright_evaluate`. Filter by `accept` so
   you grab the intended input (e.g. images vs. video vs. pdf), strip the hiding, give
   it a stable id:
   ```js
   (()=>{const e=[...document.querySelectorAll('input[type=file]')]
       .find(x=>(x.accept||'').includes('image'));   // adjust filter per target
     e.classList.remove('hidden');
     e.style.cssText='display:block;opacity:1;width:200px;height:30px;position:fixed;top:0;left:0;z-index:9999';
     e.id='qa-upload-input';return e.id;})()
   ```
2. **Upload by that id**: `playwright_upload_file` with
   `selector="#qa-upload-input"`, `filePath="/tmp/<file>"`.
3. **Make a valid throwaway file** in Bash first if you don't have one. A 70-byte 1x1
   PNG decoded from base64 satisfies JPG/PNG/WEBP `accept` filters and real image
   validation:
   ```bash
   python3 -c "import base64;open('/tmp/qa_test_photo.png','wb').write(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='))"
   ```

## Verification
- `playwright_upload_file` returns `Uploaded file '...' to '#qa-upload-input'` (no timeout).
- The app shows the file accepted (preview, count, "1 image", a draft save, etc.).
- For real delivery, read the resulting CDN/S3 URL out of the DOM
  (`document.body.innerText.match(/https:\/\/[^\s"']+/g)` or an `<img>` `src`) and
  confirm it serves:
  ```bash
  curl -s -o /dev/null -w "HTTP %{http_code} %{content_type} %{size_download}\n" "<url>"
  # expect: HTTP 200 image/png <bytes-of-your-file>
  ```

## Example
On a 6-step listing wizard (staging.doubledoor.io), the "Media & Documents" step had
three hidden inputs (`image/jpeg,image/png,image/webp`; `video/*`; `application/pdf`).
`playwright_upload_file` on `input[type=file][accept*="image/png"]` timed out
(`resolved to hidden`). Unhiding the image input + tagging it `#qa-upload-input`, then
uploading `/tmp/qa_test_photo.png`, succeeded; the page reported "You currently have 1"
and exposed a CloudFront URL that returned `HTTP 200 image/png 70`.

## Notes
- `playwright_evaluate` runs in page scope: no top-level `await` (wrap in an async IIFE).
- Pick the input by `accept`, not DOM order — order isn't guaranteed across UIs.
- Restyling the input doesn't break the app's own change handler; the framework's
  hidden `onChange` still fires on file selection.
- If the app uses a label-for-button pattern with no real `<input type=file>` in the DOM
  until interaction, click the visible button first, then re-query.
- Companion: exploratory web-app testing lives in `sdet-explore` (which points here for
  uploads).

## References
- Playwright MCP file tool: `mcp__playwright__playwright_upload_file` (selector, filePath).
- Plain Playwright `locator.setInputFiles()` handles hidden inputs natively — the
  visibility wait is specific to the MCP wrapper.
