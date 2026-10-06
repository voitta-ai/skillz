---
name: istio-multicluster-endpointless-mesh-service
description: |
  How to define an endpoint-less "away-cluster" Service for Istio multi-cluster
  (multi-primary/multi-network) endpoint merge, so cross-cluster traffic to a
  Service name routes to a REMOTE cluster's pods. Use when: (1) building a
  federated mesh where a Service must exist in cluster B but have NO local
  backends so the mesh routes to cluster A's endpoints (e.g. region-pinned
  writes, a home/away topology); (2) the away cluster ALSO runs real pods that
  share the normal app label and must NOT be selected; (3) traffic to
  <svc>.<ns>.svc.cluster.local hits an empty ClusterIP / "connection refused" /
  lands locally instead of crossing to the remote cluster. Key rule: use a
  DECOY selector that matches no pod, NOT an omitted/empty selector.
author: Claude Code
version: 1.0.0
date: 2026-07-06
source: https://github.com/voitta-ai/skillz
source_file: skills/istio-multicluster-endpointless-mesh-service/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/istio-multicluster-endpointless-mesh-service/SKILL.md`). Updates go
> through the repo's worktree + PR workflow — open an issue, branch, PR.

# Istio multi-cluster endpoint-less mesh Service (decoy selector, not omitted)

## Problem

In an Istio multi-primary / multi-network mesh, you often need a Service that
exists in **both** clusters under the same `name.namespace` but whose traffic in
one cluster ("away") must route to the **other** cluster's ("home") pods via the
east-west gateway — the away cluster has no local backends for it on purpose.

Two ways to make a Service have no local endpoints look equivalent but are not:

- **Omitted / empty selector** (`spec.selector` absent or `{}`) — the endpoints
  controller manages nothing, so **no EndpointSlice object is created at all**.
- **Decoy selector** that matches no pod (e.g. `app: <svc>-stub-no-local`) — the
  controller still creates an **empty EndpointSlice** (0 ready addresses) carrying
  the `kubernetes.io/service-name=<svc>` label.

The EndpointSlice is the object istiod anchors remote endpoints onto during the
cross-cluster merge. An omitted selector removes that anchor, so the remote
endpoints may never get merged in — the away Service resolves to an empty
ClusterIP and traffic silently fails (connection refused / no endpoints), with no
error at apply/config time.

## Context / Trigger Conditions

Reach for this when:

- Building a multi-primary/multi-network Istio mesh with a home/away Service
  topology (region-pinned writes, active/standby, "this data lives only in
  region X").
- A cross-cluster call to `<svc>.<ns>.svc.cluster.local` from the away cluster
  returns **connection refused** or hits an **empty endpoint list**, even though
  the mesh control plane reports the clusters as synced.
- The away cluster **also runs real pods** under the normal app label (e.g. its
  own regional copy of the same service) that must NOT be selected by the away
  Service — selecting them would land traffic locally instead of crossing.
- You're tempted to "clean up" a match-nothing selector into `spec.selector = {}`.

## Solution

1. **Away-cluster Service: use a decoy selector that matches no pod.** Pick a
   label value that is a reserved sentinel — nothing real ever carries it:

   ```yaml
   apiVersion: v1
   kind: Service
   metadata:
     name: my-svc            # same name.namespace as the home-cluster Service
     namespace: my-ns
   spec:
     type: ClusterIP
     selector:
       app: my-svc-stub-no-local   # DECOY: matches nothing. NOT {} and NOT omitted.
     ports:
       - name: http                # keep name/port/protocol identical to the home Service
         port: 80
         targetPort: 8080
   ```

2. **Home-cluster Service: normal real selector** (`app: my-svc`) selecting the
   local pods. This is the Service the mesh **exports** cross-cluster.

3. **Both clusters' namespaces must be meshed** (`istio-injection=enabled` and the
   pods actually sidecar-injected) — an un-injected pod bypasses Envoy and the
   whole merge, giving the same connection-refused symptom.

4. **Keep the port spec identical** across the home and away Services (name, port,
   targetPort, protocol) — protocol selection for the merge keys off the port.

5. In Terraform (per-region module), render the region-correct variant from one
   resource with a conditional selector, and **gate creation** on an explicit flag
   so it only exists where federation is actually live:

   ```hcl
   resource "kubernetes_service" "away_or_home" {
     count = var.enable_alias ? 1 : 0
     # ...
     spec {
       selector = var.region == var.home_region ? { app = local.app } : { app = "${local.app}-stub-no-local" }
       # ...
     }
   }
   ```

## Verification

- Away cluster: `kubectl --context away -n <ns> get endpointslices -l kubernetes.io/service-name=<svc>`
  shows an EndpointSlice that **exists but is empty** (with a decoy selector). With
  an omitted selector you'd see **no EndpointSlice** — that's the failure mode.
- Away cluster local endpoints empty: `kubectl --context away -n <ns> get endpoints <svc>` → no addresses.
- After mesh sync, the away Envoy cluster for `<svc>` carries the **remote** (home)
  endpoints — typically the east-west gateway IPs. A functional test: a request to
  `<svc>.<ns>.svc.cluster.local` issued from an away-cluster pod lands on a
  home-cluster pod (e.g. a write shows up in the home region only).
- Control-plane synced: `istioctl remote-clusters` (or the remote-secret) shows
  each istiod aware of its peer.

## Notes

- **The decoy label is a reserved sentinel.** The whole safety of "no local
  backends" is that no real pod ever carries it. If the away cluster runs pods
  under the normal label, the decoy value MUST be distinct from that label, and no
  future Deployment/Helm chart may reuse it — otherwise the away Service starts
  selecting local pods and traffic lands locally (a silent data-routing bug).
  Document it and, if possible, add a guard (a Terraform variable validation
  forbidding the app label from equaling the sentinel; a CI/admission check).
- **Injection is a separate, equally-silent failure.** If the away (or home) pods
  roll un-injected because the namespace lost its `istio-injection=enabled` label,
  you get the identical connection-refused symptom for a completely different
  reason. Make the namespace label durable (in IaC), not a one-shot.
- The decoy-selector approach is verified working in a multi-primary/multi-network
  mesh with east-west gateways. The omitted-selector failure is the analyzed
  reason for the EndpointSlice anchor requirement — prefer the decoy, and if you
  must use a selector-less Service, verify the merge explicitly and be ready to
  create manual EndpointSlices.

## References

- Istio: Install Multi-Primary on different networks —
  https://istio.io/latest/docs/setup/install/multicluster/multi-primary_multi-network/
- Kubernetes: Services without selectors / EndpointSlices —
  https://kubernetes.io/docs/concepts/services-networking/service/#services-without-selectors
- Kubernetes: EndpointSlices (`kubernetes.io/service-name` labeling) —
  https://kubernetes.io/docs/concepts/services-networking/endpoint-slices/
