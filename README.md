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

# 1. Start minikube and install Istio
make setup

# 2. Build images into minikube's docker daemon (IMPORTANT: must be in the same terminal)
eval $(minikube docker-env)
make build

# 3. Deploy everything
make deploy

# 4. Port-forward and test
make port-forward
```

In another terminal:
```bash
curl localhost:8000/data
curl localhost:8000/retry-demo | python3 -m json.tool
```

> **Note:** `eval $(minikube docker-env)` must be run before `make build` in the same terminal session. It points your docker CLI at minikube's internal daemon so images are available inside the cluster without pushing to a registry.

## Canary Deployment Demo

```bash
# Watch traffic split in real time
watch -n1 "curl -s localhost:8000/retry-demo | python3 -m json.tool"

# In another terminal, progressively shift traffic
make canary-10   # 90% v1 / 10% v2
make canary-50   # 50% v1 / 50% v2  ← versions_seen will show a mix
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
# Inject 5s delay into 50% of backend requests
make fault-inject

# Some calls will be fast, some will take ~5s and return 504
curl -s localhost:8000/data | python3 -m json.tool

# Clear the fault
make fault-clear
```

## Verify mTLS

```bash
make verify-mtls
# issuer=O = cluster.local  ← Istio's internal CA issued the cert
# All traffic between services is mutually authenticated
```

## Observability

```bash
make kiali    # Service graph with live traffic flow
make grafana  # Latency, error rate, RPS dashboards
```

## Project Structure

```
istio-mesh-demo/
├── services/
│   ├── frontend/        # FastAPI — calls backend, exposes /data and /retry-demo
│   └── backend/         # FastAPI — returns versioned log samples
├── k8s/
│   ├── base/            # Namespace, Deployments, Services
│   └── istio/           # VirtualService, DestinationRule, PeerAuthentication, fault injection
├── docs/
│   └── WRITEUP.md       # Design decisions and learnings
└── Makefile             # One-command setup and demo flows
```

## Makefile Reference

| Target | Description |
|---|---|
| `make setup` | Start minikube + install Istio + create namespace |
| `make build` | Build docker images into minikube's daemon |
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
