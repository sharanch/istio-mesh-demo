# istio-mesh-demo

A hands-on Istio service mesh project demonstrating production-grade traffic management, zero-trust security, and observability using two custom Python microservices on Kubernetes.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    mesh-demo namespace                       │
│                 (istio-injection: enabled)                   │
│                                                             │
│  ┌──────────────────┐   mTLS   ┌──────────────────────────┐ │
│  │    frontend      │─────────▶│   backend v1 / v2        │ │
│  │  FastAPI :8000   │          │   FastAPI :8001           │ │
│  │  sa: frontend    │          │   sa: backend             │ │
│  └──────────────────┘          └──────────────────────────┘ │
│       envoy sidecar                  envoy sidecar          │
│                                           │                 │
│                                        mTLS                 │
│                                           │                 │
│                                    ┌──────▼──────┐          │
│                                    │    Redis    │          │
│                                    │  sa: redis  │          │
│                                    └─────────────┘          │
└─────────────────────────────────────────────────────────────┘
                        │
              ┌─────────▼──────────┐
              │  Istiod (control   │
              │  plane) — xDS push │
              └────────────────────┘
```

Each pod runs `2/2` containers: your app + an Envoy sidecar injected automatically by Istio. All service-to-service traffic is mTLS encrypted without any changes to application code.

## Features

| Feature | Implementation |
|---|---|
| **mTLS** | `PeerAuthentication` STRICT — verified via `openssl` inside the sidecar |
| **Zero-trust authorization** | `AuthorizationPolicy` — frontend SA → backend only, backend SA → Redis only |
| **Canary traffic splitting** | `VirtualService` weights: 100/0 → 90/10 → 50/50 → 0/100 |
| **Fault injection** | 5s delay on 50% of backend requests — exercises frontend timeout handling |
| **Circuit breaking** | Outlier detection — pod ejected after 3 consecutive 5xx errors for 30s |
| **Retry policy** | Up to 3 attempts with 5s per-try timeout on gateway/connect failures |
| **Redis persistence** | Log entries stored as UUID-keyed Redis hashes, shared across all replicas |
| **Distributed tracing** | B3 trace headers propagated frontend → backend, stored with each log entry |
| **Custom metrics** | `logs_total` Prometheus counter labelled by level and version |
| **Observability** | Kiali service graph, Grafana dashboards, Jaeger distributed tracing |
| **CI/CD** | GitHub Actions builds and pushes to GHCR on tag push, auto-updates manifests |

## Prerequisites

- [minikube](https://minikube.sigs.k8s.io/) (v1.30+)
- [istioctl](https://istio.io/latest/docs/setup/getting-started/)
  ```bash
  curl -L https://istio.io/downloadIstio | sh -
  sudo mv istio-*/bin/istioctl /usr/local/bin/
  ```
- Docker, kubectl

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

Images are pulled from GHCR — no local build needed.

## Local Development

```bash
make setup
eval $(minikube docker-env)
make build

kubectl set image deployment/frontend frontend=istio-mesh-demo/frontend:latest -n mesh-demo
kubectl set image deployment/backend-v1 backend=istio-mesh-demo/backend:latest -n mesh-demo
kubectl set image deployment/backend-v2 backend=istio-mesh-demo/backend:latest -n mesh-demo
kubectl patch deployment frontend -n mesh-demo -p '{"spec":{"template":{"spec":{"containers":[{"name":"frontend","imagePullPolicy":"Never"}]}}}}'
kubectl patch deployment backend-v1 -n mesh-demo -p '{"spec":{"template":{"spec":{"containers":[{"name":"backend","imagePullPolicy":"Never"}]}}}}'
kubectl patch deployment backend-v2 -n mesh-demo -p '{"spec":{"template":{"spec":{"containers":[{"name":"backend","imagePullPolicy":"Never"}]}}}}'
```

## CI/CD

Pushing a version tag triggers `.github/workflows/build.yml`:

1. Builds `frontend` and `backend` images, pushes to GHCR with the tag and `latest`
2. Updates `k8s/base/frontend.yaml` and `k8s/base/backend.yaml` with the new image tag
3. Commits updated manifests back to `main`

```bash
git tag v1.2.0
git push origin v1.2.0
```

## Demo Flows

### Canary Deployment

```bash
# Watch the split in real time
watch -n1 "curl -s localhost:8000/canary-split | python3 -m json.tool"

# Shift traffic progressively in another terminal
make canary-10    # 90% v1 / 10% v2
make canary-50    # 50% v1 / 50% v2
make canary-100   # 100% v2
```

### Fault Injection

```bash
make fault-inject   # 5s delay on 50% of backend requests
curl -s localhost:8000/data | python3 -m json.tool
make fault-clear
```

### Retry Policy

```bash
make retry          # 3 attempts, 5s per-try timeout
make fault-inject   # retries absorb transient failures transparently
curl -s localhost:8000/data | python3 -m json.tool
make retry-clear
make fault-clear
```

### Circuit Breaker

Circuit breaking is enabled by default via `DestinationRule` — no separate apply needed. After 3 consecutive 5xx errors, the offending pod is ejected from load balancing for 30s.

```bash
# Trigger it by combining fault injection with heavy traffic
make fault-inject
for i in $(seq 1 20); do curl -s localhost:8000/data | python3 -m json.tool; done
make kiali   # watch the pod get ejected in the service graph
make fault-clear
```

### mTLS Toggle

```bash
make mtls-permissive   # allow plaintext (shows what without mTLS looks like)
kubectl run curl --image=curlimages/curl -n mesh-demo -it --rm \
  --annotations="sidecar.istio.io/inject=false" \
  -- curl http://backend:8001/health   # succeeds

make mtls-strict       # lock it back down
kubectl run curl --image=curlimages/curl -n mesh-demo -it --rm \
  --annotations="sidecar.istio.io/inject=false" \
  -- curl http://backend:8001/health   # connection reset
```

### Zero-Trust Authorization

```bash
# Allowed — frontend SA calling backend through the mesh
curl localhost:8000/data

# Blocked — wrong service account gets 403
kubectl run curl --image=curlimages/curl -n mesh-demo \
  --annotations="sidecar.istio.io/inject=true" \
  -it --rm -- curl http://backend:8001/data

make authz-disable   # remove policy for comparison
make authz-enable    # re-apply
```

### Verify mTLS

```bash
make verify-mtls
# issuer=O = cluster.local  ← cert issued by Istio's internal CA
```

## Log API

The frontend exposes a `/log` passthrough that routes through the mesh to the backend, which persists entries in Redis using UUID-keyed hashes.

```bash
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
    "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "level": "INFO",
    "msg": "hello from curl",
    "version": "v1",
    "timestamp": "2026-05-09T09:47:49.508430",
    "pod": "backend-v1-d798ffdf7-zn8df",
    "trace": {"x-b3-traceid": "abc123...", "x-request-id": "..."}
  }
}
```

**GET** all logs:
```bash
curl http://localhost:8000/log
```

**DELETE** a single entry:
```bash
curl -X DELETE http://localhost:8000/log/f47ac10b-58cc-4372-a567-0e02b2c3d479
```

**DELETE** all logs:
```bash
curl -X DELETE http://localhost:8000/log
```

Inspect Redis directly:
```bash
kubectl exec -n mesh-demo deploy/redis -- redis-cli KEYS "log:*"
```

The `pod` field in each entry shows which replica wrote it — useful during the canary demo:
```json
{"id": "f47ac10b-...", "version": "v1", "pod": "backend-v1-d798ffdf7-zn8df"}
{"id": "a1b2c3d4-...", "version": "v2", "pod": "backend-v2-686c747854-fsmmm"}
```

### Distributed Tracing

Each log entry stores the B3 trace headers captured at request time. Use the `x-b3-traceid` to look up the full trace in Jaeger:

```bash
make jaeger
```

## Observability

```bash
make kiali    # service graph with live traffic flow and mTLS status
make grafana  # latency, error rate, RPS dashboards
make jaeger   # distributed traces
```

## Project Structure

```
istio-mesh-demo/
├── .github/workflows/build.yml     # CI — build, push GHCR, update manifests
├── services/
│   ├── frontend/                   # FastAPI — /data, /canary-split, /log passthrough
│   └── backend/                    # FastAPI + Redis — log CRUD, custom Prometheus metrics
├── k8s/
│   ├── base/
│   │   ├── namespace.yaml
│   │   ├── frontend.yaml           # ServiceAccount + Deployment + Service
│   │   ├── backend.yaml            # ServiceAccount + v1/v2 Deployments + Service
│   │   └── redis.yaml              # ServiceAccount + Deployment + Service
│   └── istio/
│       ├── peer-authentication.yaml           # STRICT mTLS
│       ├── peer-authentication-permissive.yaml
│       ├── destination-rule.yaml              # backend (mTLS + circuit breaker + subsets) + redis (mTLS)
│       ├── authorization-policy.yaml          # frontend→backend, backend→redis
│       ├── virtual-service-100-v1.yaml
│       ├── virtual-service-canary-10.yaml
│       ├── virtual-service-canary-50.yaml
│       ├── virtual-service-canary-100-v2.yaml
│       ├── fault-injection.yaml
│       └── retry-policy.yaml
├── docs/WRITEUP.md
└── Makefile
```

## Makefile Reference

| Target | Description |
|---|---|
| `make setup` | Start minikube, install Istio, create namespace |
| `make build` | Build images into minikube daemon (local dev only) |
| `make deploy` | Apply all manifests — base + Istio resources |
| `make canary-10` | Route 10% traffic to backend v2 |
| `make canary-50` | Route 50% traffic to backend v2 |
| `make canary-100` | Route 100% traffic to backend v2 |
| `make fault-inject` | Inject 5s delay into 50% of backend requests |
| `make fault-clear` | Remove fault injection |
| `make retry` | Enable retry policy — 3 attempts, 5s per-try timeout |
| `make retry-clear` | Remove retry policy |
| `make mtls-strict` | Set PeerAuthentication to STRICT |
| `make mtls-permissive` | Set PeerAuthentication to PERMISSIVE |
| `make verify-mtls` | Confirm mTLS via openssl in the sidecar |
| `make authz-enable` | Apply AuthorizationPolicy |
| `make authz-disable` | Remove AuthorizationPolicy |
| `make port-forward` | Forward frontend to localhost:8000 |
| `make kiali` | Open Kiali dashboard |
| `make grafana` | Open Grafana dashboard |
| `make jaeger` | Open Jaeger dashboard |
| `make clean` | Delete namespace and stop minikube |

## Design Decisions

See [docs/WRITEUP.md](docs/WRITEUP.md) for full design rationale.