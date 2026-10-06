---
name: aws-http-server-on-lambda-web-adapter
description: |
  Host a small, unmodified HTTP server (Node/Python/any) as a scale-to-zero AWS
  Lambda — including LLM-proxy demo apps — using the AWS Lambda Web Adapter, and
  work around the two gotchas that bite. Use when: (1) you want an on-demand,
  ~$0-idle public URL for a plain web server without rewriting it into a Lambda
  handler; (2) a Lambda **Function URL** returns `403 AccessDeniedException`
  ("Forbidden") even though `AuthType=NONE` + the resource policy are correct and
  there is NO SCP/RCP; (3) an API Gateway HTTP API in front of a Lambda returns a
  504 / `{"message":...}` only for slow requests (an LLM call that takes 20-40s);
  (4) you need cost guardrails so a public demo can't run away. Covers the
  zero-code-change container Dockerfile, the Function-URL-vs-API-Gateway decision
  and its hard 30s-timeout tradeoff, a fast-provider-first latency fix, and the
  reserved-concurrency + budget guardrails.
author: Claude Code
version: 1.0.0
date: 2026-08-06
source: verified live deploy (Node zero-dep HTTP server + LLM waterfall, us-west-2)
source_file: DEPLOY.md of the deployed app
---

# HTTP server on Lambda via the Web Adapter (with the two gotchas)

**Canonical source:** distilled from a live deployment of a zero-dependency Node
HTTP server (static PWA + one POST endpoint proxying an LLM call) onto AWS Lambda,
fronted first by a Function URL (failed) then API Gateway (worked). Genericized;
substitute your own `<account-id>`, `<region>`, `<fn-name>`.

## 1. Run an unchanged HTTP server on Lambda (no handler rewrite)

The **AWS Lambda Web Adapter (LWA)** is a Lambda extension that translates Lambda
invokes (Function URL, API Gateway v1/v2, ALB) into plain HTTP requests to your
server on a local port. Your app needs **no code change** and still runs as a
normal container anywhere.

Dockerfile — add one COPY line; keep your normal base image and CMD:

```dockerfile
FROM node:20-slim
# The adapter as an extension; harmless when run as a plain container.
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1 /lambda-adapter /opt/extensions/lambda-adapter
WORKDIR /app
COPY . .
# LWA forwards to your app on port 8080 by default; make your server listen there.
ENV PORT=8080
EXPOSE 8080
CMD ["node", "server.js"]
```

Deploy as a **container image** Lambda:

```bash
ECR=<account-id>.dkr.ecr.<region>.amazonaws.com
aws ecr get-login-password --region <region> | docker login --username AWS --password-stdin $ECR
docker buildx build --platform linux/amd64 -t $ECR/<repo>:latest --push .   # amd64 for x86_64 Lambda
aws lambda create-function --function-name <fn-name> --package-type Image \
  --code ImageUri=$ECR/<repo>:latest --role <exec-role-arn> \
  --timeout 120 --memory-size 512 \
  --environment file://env.json          # keep secrets out of the CLI/ps
```

Notes:
- Any base image works (does NOT need an AWS Lambda base image); the adapter
  bridges the Runtime API.
- New IAM role -> `create-function` may fail for ~10-30s on role propagation;
  retry with a short sleep.

## 2. Front door: Function URL vs API Gateway

Prefer a **Lambda Function URL** — no request-duration cap (up to the 15-min
Lambda max), supports response streaming, built-in HTTPS, no extra service.

But it can fail closed: a Function URL with `AuthType=NONE` + a correct
`lambda:InvokeFunctionUrl` resource policy for `Principal:"*"` can STILL return
`403 AccessDeniedException` ("Forbidden") **with no SCP and no RCP present, even in
the Organizations management account**. Cause is an unresolved account-level quirk;
propagation retries do not fix it. Don't rabbit-hole — **pivot to API Gateway
HTTP API**, which uses `execute-api` (a different action) and is unaffected:

```bash
# Quick-create: makes the AWS_PROXY integration, $default route, default stage,
# AND the lambda invoke permission in one call.
aws apigatewayv2 create-api --name <fn-name> --protocol-type HTTP \
  --target arn:aws:lambda:<region>:<account-id>:function:<fn-name> \
  --query ApiEndpoint --output text
```

LWA auto-detects the event shape, so the SAME image works behind Function URL,
API Gateway v2, or ALB with no change.

## 3. Gotcha: API Gateway HTTP API has a HARD 30s integration timeout

It cannot be raised for HTTP APIs. A fast request (short input, ~10-15s) returns
200; a slow one (a free-tier LLM call at 20-40s) 504s with a lowercase
`{"message":...}` envelope. Diagnose by **timing the call** — a clean cut near
~30s is the timeout, not your app (your app returns 200 on the same route with a
smaller input).

Fixes, in order:
- **Make the upstream faster.** For an LLM proxy, put a fast provider first in your
  cascade (e.g. Groq ~2-5s) instead of a slow free slug (~20-40s). Latency, not the
  front door, is the real problem.
- Use response streaming, or the Function URL (no cap) if you can get it working.
- REST API (not HTTP API) can raise the integration timeout via a quota increase;
  heavier, usually not worth it for a demo.

## 4. Cost guardrails for a public demo (make runaway structurally impossible)

- **Reserved concurrency = 2** (`put-function-concurrency`): free, and hard-caps
  parallel invokes -> caps blast radius. This is the key guard.
- **Scale-to-zero = $0 idle** (reserved concurrency is free; only *provisioned*
  concurrency costs).
- 512 MB / 120s timeout keeps per-invoke cost tiny. Lambda bills **wall-clock**,
  so a synchronous wait on a slow model IS billed — but at 512MB it's ~$0.0001/call.
- Free-tier model = **$0 model ceiling** (quota dies before dollars). The only real
  runaway lever is switching to a *paid* model.
- **AWS Budget** ($5/mo, email alert at 80%) as a backstop tripwire.

## 5. Auth for a public demo without a login UI

Gate only the expensive path; keep static assets public:

- Server: if `AUTH_TOKEN` env is set, require `?key=<token>` on `POST /api/<expensive>`;
  unset = open (local dev).
- Client: `fetch('/api/<expensive>' + window.location.search, ...)` so opening the
  page at `…/?key=SECRET` forwards the token with no extra UI.
- Token lives in the Lambda env var (retrievable via `get-function-configuration`);
  never commit it.

## Verification

Live-tested: static `GET /` 200; `POST` without key 401; with key 200 + valid JSON
in ~15s via API Gateway; a ~40s input 504'd at the 30s cap (confirming the gotcha);
the Function URL 403'd anonymously AND SigV4-signed with no SCP/RCP on the mgmt
account. Idle cost measured at ~$0.01/mo (ECR image storage), sub-$1 under demo use.
