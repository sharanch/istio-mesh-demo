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
2. Updates `k8s/base/frontend.yaml` and `k8s/base/backend.yaml` to reference the new GHCR image and sets `imagePullPolicy: Always`
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
│   ├── frontend/            # FastAPI — calls backend, exposes /data and /canary-split
│   └── backend/             # FastAPI — returns versioned log samples
├── k8s/
│   ├── base/                # Namespace, Deployments, Services
│   └── istio/               # VirtualService, DestinationRule, PeerAuthentication, fault injection
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
| `make verify-mtls` | Confirm mTLS via openssl in the sidecar |
| `make port-forward` | Forward frontend to localhost:8000 |
| `make kiali` | Open Kiali service graph dashboard |
| `make grafana` | Open Grafana metrics dashboard |
| `make clean` | Delete namespace and stop minikube |

## Design Decisions

See [docs/WRITEUP.md](docs/WRITEUP.md) for a full explanation of design decisions.