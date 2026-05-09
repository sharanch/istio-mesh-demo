# Design Decisions & Learnings

## Why Istio over Linkerd?
Istio has a steeper ops cost (more CRDs, heavier control plane) but provides
the full feature set used in production at scale: fine-grained VirtualService
routing, fault injection, WASM extensibility, and first-class Kiali integration.
For a portfolio project, Istio is also more recognizable on a resume.

## Why custom Python services?
Using off-the-shelf demo apps (bookinfo, emojivoto) hides the full stack.
Writing the services means understanding exactly what traffic is flowing and why
the mesh config is doing what it is. The backend returns structured log samples,
nodding to SRE-style observability work.

## mTLS STRICT mode
Permissive mode allows plaintext — useful for migration, not for showcasing security.
STRICT mode means any pod without a sidecar cannot talk to services in this namespace.
Verified with `openssl` directly inside the istio-proxy container, showing the
Istio-issued certificate in the TLS handshake.

## Fault injection as SRE practice
Injecting delays rather than errors lets you verify timeout handling and
frontend graceful degradation. A 504 with a clear error body is better than
a hanging connection. This maps directly to chaos engineering practices used
in production SRE environments.

## Canary via VirtualService weights
Kubernetes-native rollouts (RollingUpdate) don't let you control traffic percentage
independently of replica count. Istio VirtualService weights decouple these entirely —
you can have 1 v2 replica receiving 10% of traffic regardless of how many v1 replicas exist.
This is how teams run true progressive delivery without scaling up replicas just to shift traffic.

## Prometheus instrumentation
Both services use `prometheus-fastapi-instrumentator` which auto-exposes `/metrics`
in Prometheus format. Istio's Grafana picks these up automatically — no manual scrape
config needed in the demo profile.
