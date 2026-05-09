# istio-mesh-demo

A hands-on Istio service mesh project demonstrating production-grade traffic management, security, and observability using two custom Python microservices on Kubernetes.

## Architecture

```
┌─────────────────────────────────────────────┐
│           mesh-demo namespace                │
│  (istio-injection: enabled)                  │
│                                             │
│  ┌──────────────┐      ┌──────────────────┐ │
│  │   frontend   │─────▶│  backend v1 / v2 │ │
│  │  FastAPI :8000│ mTLS │   FastAPI :8001  │ │
│  └──────────────┘      └──────────────────┘ │
│        │                       │            │
│   envoy sidecar           envoy sidecar     │
│                                │            │
│                         ┌──────▼──────┐     │
│                         │    Redis    │     │
│                         └─────────────┘     │
└─────────────────────────────────────────────┘
              │           │
         ┌────▼───────────▼────┐
         │   Istio Control     │
         │   Plane (istiod)    │
         └─────────────────────┘
```

Each pod runs `2/2` containers: your app + an Envoy sidecar injected automatically by Istio. All service-to-service traffic is mTLS encrypted without any changes to application code.

## Features

| Feature | How it's demonstrated |
|---|---|
| **mTLS** | `PeerAuthentication` STRICT mode — verified via `openssl` in the sidecar |
| **Authorization** | `AuthorizationPolicy` — only frontend service account can call backend |
| **Traffic splitting** | `VirtualService` weights: 100/0 → 90/10 → 50/50 → 0/100 |
| **Fault injection** | 5s delay on 50% of backend requests, frontend handles gracefully |
| **Observability** | Kiali service graph, Grafana latency dashboards |
| **CI/CD** | GitHub Actions builds and pushes images to GHCR on tag push, auto-updates manifests |

## Prerequisites

- [minikube](https://minikube.sigs.k8s.io/) (v1.30+)
- [istioctl](https://istio.io/latest/docs/setup/getting-started/) — install with:
  ```bash
  curl -L https://istio.io/downloadIstio | sh -
  sudo mv istio-*/bin/istioctl /usr/local/bin/
  ```
- Docker
- kubectl

## Quickstart

```bash
git clone https://github.com/sharanch/istio-mesh-demo
cd istio-mesh-demo

make setup
make deploy
make port-forward
```

In another terminal:
```bash
curl localhost:8000/data
curl localhost:8000/canary-split | python3 -m json.tool
```

Images are pulled from GHCR (`ghcr.io/sharanch/istio-mesh-demo`). No local build needed.

## Local Development

To build and test without pushing to GHCR, build images directly into minikube's docker daemon:

```bash
make setup

# Must be run in the same terminal session as make build
eval $(minikube docker-env)
make build

# Temporarily patch manifests to use local images
kubectl set image deployment/frontend frontend=istio-mesh-demo/frontend:latest -n mesh-demo
kubectl set image deployment/backend-v1 backend=istio-mesh-demo/backend:latest -n mesh-demo
kubectl set image deployment/backend-v2 backend=istio-mesh-demo/backend:latest -n mesh-demo
kubectl patch deployment frontend -n mesh-demo -p '{"spec":{"template":{"spec":{"containers":[{"name":"frontend","imagePullPolicy":"Never"}]}}}}'
kubectl patch deployment backend-v1 -n mesh-demo -p '{"spec":{"template":{"spec":{"containers":[{"name":"backend","imagePullPolicy":"Never"}]}}}}'
kubectl patch deployment backend-v2 -n mesh-demo -p '{"spec":{"template":{"spec":{"containers":[{"name":"backend","imagePullPolicy":"Never"}]}}}}'
```

## CI/CD

Pushing a version tag triggers `.github/workflows/build.yml` which:

1. Builds `frontend` and `backend` images and pushes to GHCR with the tag version and `latest`
2. Updates `k8s/base/frontend.yaml` and `k8s/base/backend.yaml` to reference the new GHCR image tag
3. Commits the updated manifests back to `main`

```bash
git tag v1.1.0
git push origin v1.1.0
# → images pushed to ghcr.io/sharanch/istio-mesh-demo/frontend:v1.1.0
# → manifests updated and committed automatically
```

## Canary Deployment Demo

```bash
# Watch traffic split in real time
watch -n1 "curl -s localhost:8000/canary-split | python3 -m json.tool"

# In another terminal, progressively shift traffic
make canary-10   # 90% v1 / 10% v2
make canary-50   # 50% v1 / 50% v2
make canary-100  # 100% v2
```

Example output at 50/50:
```json
{
    "calls": 5,
    "versions_seen": ["v1", "v1", "v2", "v1", "v2"]
}
```

## Fault Injection Demo

```bash
make fault-inject

# Some calls fast, some ~5s and return 504
curl -s localhost:8000/data | python3 -m json.tool

make fault-clear
```

## Verify mTLS

```bash
make verify-mtls
# issuer=O = cluster.local  ← Istio's internal CA issued the cert
```

## Zero-Trust Demo

AuthorizationPolicy is applied by default on `make deploy`. Only the `frontend` service account is allowed to call backend.

```bash
# Allowed — frontend calling backend through the mesh
curl localhost:8000/data

# Blocked — pod with sidecar but wrong service account gets 403
kubectl run curl --image=curlimages/curl -n mesh-demo \
  --annotations="sidecar.istio.io/inject=true" \
  -it --rm -- curl http://backend:8001/data

# Toggle off/on for comparison
make authz-disable
make authz-enable
```

## Log API

The frontend exposes a `/log` passthrough that routes through the mesh to the backend, which persists entries in Redis. Redis is not directly reachable from outside the cluster — all access goes through the service chain.

```bash
# make sure port-forward is running first
make port-forward
```

**POST** a log entry:
```bash
curl -X POST http://localhost:8000/log \
  -H "Content-Type: application/json" \
  -d '{"level": "INFO", "msg": "hello from curl"}'
```
```json
{
  "stored": 1,
  "entry": {
    "level": "INFO",
    "msg": "hello from curl",
    "version": "v1",
    "timestamp": "2026-05-09T09:47:49.508430",
    "pod": "backend-v1-d798ffdf7-zn8df"
  }
}
```

**GET** all stored logs:
```bash
curl http://localhost:8000/log
```
```json
{
  "logs": [
    {
      "level": "INFO",
      "msg": "hello from curl",
      "version": "v1",
      "timestamp": "2026-05-09T09:47:49.508430",
      "pod": "backend-v1-d798ffdf7-zn8df"
    }
  ],
  "total": 1
}
```

**DELETE** a single log entry by ID:
```bash
curl -X DELETE http://localhost:8000/log/f47ac10b-58cc-4372-a567-0e02b2c3d479
```
```json
{"deleted": "f47ac10b-58cc-4372-a567-0e02b2c3d479"}
```

**DELETE** all logs:
```bash
curl -X DELETE http://localhost:8000/log
```
```json
{"status": "cleared"}
```

To inspect Redis directly (cluster-internal only):
```bash
kubectl exec -n mesh-demo deploy/redis -- redis-cli KEYS "log:*"
```

**Scaling behaviour:** each log entry is stored as an individual Redis key (`log:<uuid>`) with a separate index list tracking insertion order. All backend replicas write to the same Redis instance, so entries are stable and addressable by ID regardless of which pod handles the request. The `pod` field in each entry tells you exactly which replica wrote it -- useful when running the canary demo, where you'll see both v1 and v2 pods appearing across entries:

```json
{"id": "f47ac10b-...", "level": "INFO", "msg": "hello", "version": "v1", "pod": "backend-v1-d798ffdf7-zn8df"}
{"id": "a1b2c3d4-...", "level": "INFO", "msg": "hello", "version": "v2", "pod": "backend-v2-686c747854-fsmmm"}
```

## Observability

```bash
make kiali    # Service graph with live traffic flow
make grafana  # Latency, error rate, RPS dashboards
```

## Project Structure

```
istio-mesh-demo/
├── .github/
│   └── workflows/
│       └── build.yml        # Build + push to GHCR on tag, auto-update manifests
├── services/
│   ├── frontend/            # FastAPI — calls backend, exposes /data, /canary-split, /log
│   └── backend/             # FastAPI + Redis — stores and serves log entries
├── k8s/
│   ├── base/                # Namespace, Deployments, Services
│   └── istio/               # VirtualService, DestinationRule, PeerAuthentication, AuthorizationPolicy, fault injection
├── docs/
│   └── WRITEUP.md           # Design decisions and learnings
└── Makefile                 # One-command setup and demo flows
```

## Makefile Reference

| Target | Description |
|---|---|
| `make setup` | Start minikube + install Istio + create namespace |
| `make build` | Build docker images into minikube's daemon (local dev only) |
| `make deploy` | Apply all k8s and Istio manifests |
| `make canary-10` | Route 10% of traffic to backend v2 |
| `make canary-50` | Route 50% of traffic to backend v2 |
| `make canary-100` | Route 100% of traffic to backend v2 |
| `make fault-inject` | Inject 5s delay into 50% of backend requests |
| `make fault-clear` | Remove fault injection |
| `make circuit-breaker` | Enable circuit breaker — ejects pod after 3 consecutive 5xx errors |
| `make circuit-breaker-clear` | Remove circuit breaker |
| `make retry` | Enable retry policy — up to 3 attempts with 5s per-try timeout |
| `make retry-clear` | Remove retry policy |
| `make mtls-strict` | Set PeerAuthentication to STRICT — plaintext rejected |
| `make mtls-permissive` | Set PeerAuthentication to PERMISSIVE — plaintext allowed |
| `make verify-mtls` | Confirm mTLS via openssl in the sidecar |
| `make authz-enable` | Apply AuthorizationPolicy — only frontend can call backend |
| `make authz-disable` | Remove AuthorizationPolicy |
| `make port-forward` | Forward frontend to localhost:8000 |
| `make kiali` | Open Kiali service graph dashboard |
| `make grafana` | Open Grafana metrics dashboard |
| `make jaeger` | Open Jaeger distributed tracing dashboard |
| `make clean` | Delete namespace and stop minikube |

## Circuit Breaker Demo

```bash
make circuit-breaker

# Inject faults to trigger the breaker
make fault-inject

# Hammer the backend — after 3 consecutive 5xx the pod is ejected for 30s
for i in $(seq 1 20); do curl -s localhost:8000/data | python3 -m json.tool; done

# Watch the outlier detection in Kiali
make kiali

make circuit-breaker-clear
make fault-clear
```

## Retry Policy Demo

```bash
# Apply retry policy (3 attempts, 5s per-try timeout)
make retry

# Combine with fault injection — retries absorb transient failures transparently
make fault-inject
curl -s localhost:8000/data | python3 -m json.tool

make retry-clear
make fault-clear
```

## mTLS Toggle Demo

```bash
# Switch to PERMISSIVE — plaintext traffic now allowed
make mtls-permissive

# A pod without a sidecar can now reach the backend directly
kubectl run curl --image=curlimages/curl -n mesh-demo -it --rm   --annotations="sidecar.istio.io/inject=false"   -- curl http://backend:8001/health

# Lock it back down to STRICT
make mtls-strict

# Same call now fails — no mTLS cert, connection rejected
kubectl run curl --image=curlimages/curl -n mesh-demo -it --rm   --annotations="sidecar.istio.io/inject=false"   -- curl http://backend:8001/health
```

## Distributed Tracing

Log entries store the Istio B3 trace headers captured at the backend. You can correlate a log entry directly with a Jaeger trace:

```bash
# Post a log entry
curl -X POST http://localhost:8000/log   -H "Content-Type: application/json"   -d '{"level": "INFO", "msg": "trace this"}'

# The response includes the trace context
# {
#   "entry": {
#     "trace": {
#       "x-request-id": "abc-123",
#       "x-b3-traceid": "abc123def456",
#       ...
#     }
#   }
# }

# Open Jaeger and search by trace ID
make jaeger
```

## Design Decisions

See [docs/WRITEUP.md](docs/WRITEUP.md) for a full explanation of design decisions.