# Design Decisions & Learnings

## Why Istio over Linkerd?
Istio has a steeper ops cost (more CRDs, heavier control plane) but provides the full
feature set used in production at scale: fine-grained VirtualService routing, fault
injection, WASM extensibility, and first-class Kiali integration. For a portfolio
project, Istio is also more recognizable on a resume.

## Why custom Python services?
Using off-the-shelf demo apps (bookinfo, emojivoto) hides the full stack. Writing the
services means understanding exactly what traffic is flowing and why the mesh config is
doing what it is. The backend returns structured log samples, nodding to SRE-style
observability work.

## mTLS STRICT mode
Permissive mode allows plaintext — useful for migration, not for showcasing security.
STRICT mode means any pod without a sidecar cannot talk to services in this namespace.
Verified with `openssl` directly inside the istio-proxy container, showing the
Istio-issued certificate (`issuer=O = cluster.local`) in the TLS handshake.

## Fault injection as SRE practice
Injecting delays rather than errors lets you verify timeout handling and frontend graceful
degradation. A 504 with a clear error body is better than a hanging connection. This maps
directly to chaos engineering practices used in production SRE environments.

## Canary via VirtualService weights
Kubernetes-native rollouts (RollingUpdate) don't let you control traffic percentage
independently of replica count. Istio VirtualService weights decouple these entirely —
you can have 1 v2 replica receiving 10% of traffic regardless of how many v1 replicas
exist. This is how teams run true progressive delivery without scaling up replicas just
to shift traffic.

## Prometheus instrumentation
Both services use `prometheus-fastapi-instrumentator` which auto-exposes `/metrics` in
Prometheus format without any manual scrape config. The backend additionally defines a
custom `logs_total` counter labelled by `level` and `version`, enabling PromQL queries
like `rate(logs_total{level="ERROR"}[5m])` to alert on error log rate per service version.

## AuthorizationPolicy and zero-trust
mTLS gives every pod a verified identity (via Istiod-issued certificates) but does not
restrict who can talk to whom. Without AuthorizationPolicy, any pod in the mesh with a
valid cert can call any other pod.

AuthorizationPolicy adds the access control layer:
- Only the `frontend` service account can call backend (GET/POST/DELETE on /data, /health, /metrics, /log)
- Only the `backend` service account can reach Redis

This is what zero-trust actually means: identity (mTLS/PeerAuthentication) plus policy
(AuthorizationPolicy). A dedicated ServiceAccount is created for each workload and
assigned in the Deployment so Istio can identify callers by principal rather than
relying on the shared `default` service account.

## Circuit breaking via DestinationRule
Rather than maintaining a separate `circuit-breaker.yaml`, outlier detection settings
are merged into `destination-rule.yaml` alongside the mTLS config and subset definitions.
This avoids the Istio behaviour of merging two DestinationRules for the same host in
unpredictable ways, and keeps all backend traffic policy in one place.

Settings: eject a pod after 3 consecutive 5xx errors, for 30s, with up to 100% of pods
ejectable. Paired with fault injection, this demonstrates automatic removal of unhealthy
endpoints from the load balancing pool.

## Redis DestinationRule
A DestinationRule for Redis is included alongside the backend rule in `destination-rule.yaml`.
This enforces ISTIO_MUTUAL on the backend → Redis leg, completing the mTLS chain across
all three hops: frontend → backend → Redis. Connection pool is limited to 5 connections
with a 3s connect timeout — Redis is single-threaded, so hammering it with connections
adds no benefit and a tight timeout fails fast on connectivity issues.

## Retry policy
`retryOn: gateway-error,connect-failure,retriable-4xx` covers the common transient failure
modes. `perTryTimeout: 5s` with 3 attempts means worst-case 15s before giving up.
Note: this exceeds the frontend's `httpx timeout=10.0` — in production, the mesh-level
timeout should be the authoritative one and the application timeout should be removed or
raised above `perTryTimeout * attempts`.

## Distributed tracing header propagation
Istio injects B3 trace headers (`x-b3-traceid`, `x-b3-spanid` etc.) at the ingress point.
For Jaeger to stitch a full trace across multiple hops, each service must propagate these
headers to its downstream calls — Envoy cannot do this automatically because it doesn't
know which outbound call corresponds to which inbound request.

Both services extract and forward these headers explicitly. The backend also stores them
with each log entry, enabling direct correlation between a log record and its Jaeger trace.

## Redis log storage model
Each log entry is stored as an individual Redis key (`log:<uuid>`) rather than appended
to a single list. A separate index list (`log:index`) tracks insertion order. This enables
O(1) individual deletes by ID without scanning the entire dataset, while preserving
ordered retrieval via `LRANGE`. The `pod` and `version` fields in each entry are useful
during the canary demo — you can see entries written by both v1 and v2 replicas to the
same shared store.