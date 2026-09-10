---
name: oauth-mint-counting-passthrough-proxy
description: |
  Integration-test an OAuth2 client-credentials caller END TO END while asserting how often it
  mints tokens, by pointing its config-driven token endpoint at a counting pass-through proxy
  the spec starts (JDK com.sun.net.httpserver on an ephemeral port) instead of mocking the
  transport. Use when: (1) a service caches or refreshes a bearer and its unit specs stub the
  HTTP layer, so a per-request-mint or never-refresh defect is invisible; (2) you must prove in
  one run that the real gateway rejects a missing bearer, accepts a minted one, refreshes a
  stale one, AND that N calls mint once; (3) the token endpoint is read from configuration.
  Caught a real "three lookups, three mints" defect that 22 green unit specs missed.
author: Claude Code
version: 1.0.0
date: 2026-09-10
---

# Count token mints through a pass-through proxy in an integration spec

## Problem

A caller that acquires a bearer via OAuth2 client-credentials has three behaviours that only
show up against the real gateway: it must attach a cached token proactively, mint only once per
token lifetime, and refresh when the gateway rejects a stale token. Unit specs stub the
transport, so they pass whether the caller mints once or on every request. A plain end-to-end
run proves the token works but says nothing about how many were minted, and the gateway does
not tell you either.

## Context / Trigger Conditions

- Caller code mints via an endpoint read from configuration (`tokenEndpoint`, `issuer`, ...).
- Unit specs are green but replace the HTTP call to the token endpoint with a stub or spy.
- You need one run that proves: no bearer -> 401 from the gateway; bearer -> 200; stale bearer
  -> refresh and 200; N calls -> 1 mint.
- The symptom that motivates it: latency doubles on every call after a gateway cutover, or the
  token endpoint's rate limit trips, with every unit test passing.

## Solution

1. **Start a pass-through proxy inside the spec** on `127.0.0.1:0` (ephemeral port). The handler
   increments a counter, forwards the POST body plus `Content-Type` and `Authorization` to the
   REAL token endpoint, and relays status and body back. Pass-through, not mock: the real
   issuer still signs the token, so the real gateway still validates it downstream.
2. **Point the caller's configured token endpoint at the proxy**
   (`http://127.0.0.1:<port>/oauth2/token`). Everything else stays real: gateway URL, client id
   and secret, any legacy credential sent alongside.
3. **Gate on environment** (`@Requires({ env.X })` in Spock, `assumeTrue` elsewhere) so CI
   without credentials skips the spec instead of failing it, and document the one-liner that
   exports the credentials from the secret store.
4. **Assert with deltas, not absolutes.** Capture `before = mints.get()` in every feature so
   the features are order-independent and a shared counter is safe.
5. **Four features**, in this order of value:
   - the no-bearer path is rejected with a status the caller carries out (a 401 distinguishable
     from an empty result), zero mints;
   - the configured path resolves, exactly one mint;
   - N calls on one service instance, exactly one mint (the caching contract);
   - poison the cached token (direct field write: Groovy `svc.@provider.@cached = "expired"`,
     reflection in Java), call again: one mint and success (the post-expiry refresh contract).

```groovy
@Requires({ env.IT_CLIENT_ID && env.IT_CLIENT_SECRET && env.IT_TOKEN_ENDPOINT })
class CallerGatewayIntegrationSpec extends Specification {

    @Shared HttpServer proxy
    @Shared AtomicInteger mints = new AtomicInteger()

    def setupSpec() {
        URL upstream = new URL(System.getenv("IT_TOKEN_ENDPOINT"))
        proxy = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0)
        proxy.createContext("/oauth2/token") { HttpExchange ex ->
            mints.incrementAndGet()
            HttpURLConnection c = (HttpURLConnection) upstream.openConnection()
            c.requestMethod = "POST"
            c.doOutput = true
            ["Content-Type", "Authorization"].each { String h ->
                String v = ex.requestHeaders.getFirst(h)
                if (v) {
                    c.setRequestProperty(h, v)
                }
            }
            c.outputStream.withStream { it << ex.requestBody.bytes }
            int code = c.responseCode
            byte[] body = (code < 400 ? c.inputStream : c.errorStream).bytes
            ex.sendResponseHeaders(code, body.length)
            ex.responseBody.withStream { it << body }
        }
        proxy.start()
    }

    def cleanupSpec() {
        proxy?.stop(0)
    }

    void "N lookups on one instance mint once"() {
        given:
        def svc = serviceWithTokenEndpoint("http://127.0.0.1:${proxy.address.port}/oauth2/token")
        int before = mints.get()

        when:
        List results = (1..3).collect { svc.lookup("8.8.8.8") }

        then:
        results.every { !it.error }
        mints.get() - before == 1
    }
}
```

## Verification

- The mint feature goes RED against a caller that mints per request (delta == N) and GREEN
  once the cached token is attached proactively. Run it against the defective build first if
  you can; a spec that has never failed proves nothing.
- Confirm the spec was actually discovered: a `--tests` filter printing `No tests found`, or a
  results XML with `tests="0"`, means the task is not on the JUnit Platform. Spock 2 and JUnit 5
  need `useJUnitPlatform()` on that task, and integration-test tasks are often left without it.

## Example

A Grails caller of a service behind an API gateway (client-credentials against a managed
identity provider, one-hour tokens). All 22 unit specs green. The proxy spec showed three
lookups, three mints: after a refactor to an OkHttp `Authenticator`, nothing read the
provider's cached token, so every call hit the gateway without a bearer, was answered 401, and
force-minted on the retry. A three-line change (attach the cached bearer in the header
builder) took the delta to 1; the post-expiry feature then proved a poisoned cache refreshes on
the 401 and still succeeds.

## Notes

- Forward only `Content-Type`, `Authorization` (basic client auth) and the form body; do not
  relay `Host` or hop-by-hop headers.
- A 502 from the gateway with a valid token is the upstream, not auth. Check the target
  service is Ready before reading it as a token problem.
- Keep the proxy out of production code: no seam, no flag. The config-driven endpoint IS the
  seam.
- `MockWebServer` or WireMock in proxy mode do the same job, but the JDK server needs no
  dependency and cannot drift from what the caller really does.

## References

- JDK `com.sun.net.httpserver.HttpServer`:
  https://docs.oracle.com/en/java/javase/11/docs/api/jdk.httpserver/com/sun/net/httpserver/HttpServer.html
- Spock `@Requires`: https://spockframework.org/spock/docs/2.3/extensions.html#_requires
- Gradle `Test.useJUnitPlatform()`:
  https://docs.gradle.org/current/javadoc/org/gradle/api/tasks/testing/Test.html#useJUnitPlatform--
