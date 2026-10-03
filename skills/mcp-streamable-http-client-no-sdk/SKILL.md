---
name: mcp-streamable-http-client-no-sdk
description: |
  Call an MCP (Model Context Protocol) server over Streamable HTTP from your own
  code without the MCP SDK -- just an HTTP client that can POST and read a body.
  Use when: (1) you need to list or call a remote MCP server's tools from a
  language/runtime where pulling the official SDK (and its asyncio stack) is not
  worth it for a couple of calls; (2) a server exposes only an MCP endpoint
  (e.g. a path ending /mcp) and no plain REST; (3) your POST to that endpoint
  returns an SSE body (lines beginning "data:") instead of a single JSON object
  and a naive json.loads() fails; (4) tools/list or tools/call "returns nothing"
  because you read the first SSE frame instead of the result frame, or did not
  send an Accept header the server honors; (5) a tools/call result looks empty
  because the content is a list of typed parts you did not join. Covers the
  initialize -> tools/list -> tools/call sequence, the SSE framing, optional
  mcp-session-id handling, and isError.
author: Claude Code
version: 1.0.0
date: 2026-10-03
---

# Speaking MCP Streamable HTTP without the SDK

## Problem

You want to list and call a remote MCP server's tools from your own program, but
the official MCP SDK is heavier than the job: it pulls an async stack and a
dependency tree for what is two or three request/response round-trips against a
known endpoint. The transport is simple enough to speak directly -- once you know
its three non-obvious edges.

## Context / Trigger Conditions

- A server advertises an MCP endpoint over HTTP ("Streamable HTTP"), typically a
  URL whose path ends in `/mcp`.
- A plain `POST {json}` to it and `json.loads(response)` fails, or the body comes
  back as lines starting with `data:` (Server-Sent Events).
- `tools/list` or `tools/call` "returns nothing", or a tool result looks empty.
- You are in a runtime where adding the MCP SDK is disproportionate (a shell
  script, a small service, an agent host wiring one or two servers).

## Solution

MCP over Streamable HTTP is JSON-RPC 2.0, one HTTP POST per request, with the
response delivered as an SSE body. Three things trip people up:

1. **Accept both content types.** Send
   `Accept: application/json, text/event-stream`. The server picks SSE; without
   the header some servers refuse.
2. **The response is SSE, not a JSON object.** Read every line beginning
   `data:`, JSON-parse each payload, and keep the frame that carries `result`
   (or `error`). A single logical response can arrive as several `data:` frames;
   the one you want is the last/result frame, not the first. `[DONE]` and empty
   lines are not JSON.
3. **Carry a session id only if the server gives one.** Some servers return an
   `mcp-session-id` response header on `initialize` and expect it echoed on
   later calls; others assign none. Read it from the initialize response and
   send it back when present -- do not invent or require it.

Sequence:

- `initialize` (params: `protocolVersion`, `capabilities: {}`, `clientInfo`).
  Capture any `mcp-session-id` header. A spec-conformant client also sends a
  `notifications/initialized` after, but many servers do not require it before
  `tools/list`.
- `tools/list` -> `result.tools[]`, each `{name, description, inputSchema}`.
- `tools/call` (params: `{name, arguments}`) -> `result`. The human-readable
  output is `result.content`, a **list of typed parts**; join the `text` of the
  parts whose `type == "text"`. Check `result.isError` -- a failed tool call can
  still come back HTTP 200 with `isError: true`.

## Example

A dependency-free Python client (standard library only):

```python
import json, urllib.request, urllib.error

def _post(url, headers, payload, timeout=30):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", "replace")
        session = resp.headers.get("mcp-session-id")
    frame = None
    for line in body.splitlines():
        if line.startswith("data:"):
            raw = line[5:].strip()
            if raw and raw != "[DONE]":
                try:
                    frame = json.loads(raw)       # keep the LAST data frame
                except ValueError:
                    pass
    if frame is None:                              # some servers reply plain JSON
        frame = json.loads(body)
    if isinstance(frame, dict) and frame.get("error"):
        raise RuntimeError(f"MCP error: {frame['error']}")
    return frame.get("result", {}), session

def _headers(session=None):
    h = {"Content-Type": "application/json",
         "Accept": "application/json, text/event-stream"}
    if session:
        h["mcp-session-id"] = session
    return h

def _rpc(url, method, params, session=None, _id=1):
    return _post(url, _headers(session),
                 {"jsonrpc": "2.0", "id": _id, "method": method, "params": params})

def list_tools(url):
    _r, session = _rpc(url, "initialize", {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "my-client", "version": "1"}})
    result, _s = _rpc(url, "tools/list", {}, session, _id=2)
    return result.get("tools", [])

def call_tool(url, name, arguments):
    _r, session = _rpc(url, "initialize", {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "my-client", "version": "1"}})
    result, _s = _rpc(url, "tools/call",
                      {"name": name, "arguments": arguments or {}}, session, _id=3)
    if result.get("isError"):
        parts = [p.get("text", "") for p in (result.get("content") or [])
                 if p.get("type") == "text"]
        raise RuntimeError(f"tool '{name}' failed: {' '.join(parts) or 'no detail'}")
    text = "\n".join(p.get("text", "") for p in (result.get("content") or [])
                     if p.get("type") == "text")
    return text or json.dumps(result.get("structuredContent") or result)
```

The same shape translates to `curl`:

```bash
curl -s -X POST "$URL" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"c","version":"1"}}}' \
  | sed -n 's/^data: //p' | tail -1 | jq .result.serverInfo
```

## Verification

- `initialize` returns `result.serverInfo` with the server's name/version.
- `tools/list` returns a non-empty `tools[]` for a server that has tools.
- A known `tools/call` returns the expected text, and a deliberately bad call
  returns `isError: true` rather than throwing at the HTTP layer.

## Notes

- `protocolVersion` "2024-11-05" is widely accepted; a server may negotiate a
  different one back in the initialize result -- read it rather than assuming.
- Keep `id` values distinct per request within a session; the examples use fixed
  ids because each call here is its own short exchange.
- If you need many calls, reuse one session id and one connection rather than
  re-initializing each time.
- This is the HTTP (Streamable HTTP) transport. The older stdio transport and
  the deprecated HTTP+SSE two-endpoint transport are different; this targets the
  single-endpoint Streamable HTTP a modern server exposes.
- A server that returns a plain JSON object (no `data:` lines) is handled by the
  fallback `json.loads(body)` above.

## References

- MCP specification, Transports (Streamable HTTP): https://modelcontextprotocol.io/specification
- JSON-RPC 2.0: https://www.jsonrpc.org/specification
