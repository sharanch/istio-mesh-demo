NAMESPACE=mesh-demo
FRONTEND_IMG=istio-mesh-demo/frontend:latest
BACKEND_IMG=istio-mesh-demo/backend:latest

.PHONY: all setup build deploy \
        canary-10 canary-50 canary-100 \
        fault-inject fault-clear \
        circuit-breaker circuit-breaker-clear \
        retry retry-clear \
        mtls-strict mtls-permissive verify-mtls \
        authz-enable authz-disable \
        port-forward kiali grafana jaeger clean

all: setup build deploy

setup:
	minikube start --cpus=4 --memory=6144 --driver=docker
	istioctl install --set profile=demo -y
	kubectl wait --for=condition=available deployment/istiod -n istio-system --timeout=120s
	kubectl apply -f k8s/base/namespace.yaml
	kubectl label namespace $(NAMESPACE) istio-injection=enabled --overwrite

build:
	eval $$(minikube docker-env) && \
	docker build -t $(FRONTEND_IMG) services/frontend/ && \
	docker build -t $(BACKEND_IMG) services/backend/

deploy:
	kubectl apply -f k8s/base/namespace.yaml
	kubectl label namespace $(NAMESPACE) istio-injection=enabled --overwrite
	kubectl wait --for=jsonpath='{.status.phase}'=Active namespace/$(NAMESPACE) --timeout=30s
	kubectl apply -f k8s/base/backend.yaml
	kubectl apply -f k8s/base/redis.yaml
	kubectl apply -f k8s/base/frontend.yaml
	kubectl apply -f k8s/istio/peer-authentication.yaml
	kubectl apply -f k8s/istio/destination-rule.yaml
	kubectl apply -f k8s/istio/virtual-service-100-v1.yaml
	kubectl apply -f k8s/istio/authorization-policy.yaml
	kubectl rollout status deployment/frontend -n $(NAMESPACE)
	kubectl rollout status deployment/backend-v1 -n $(NAMESPACE)
	kubectl rollout status deployment/backend-v2 -n $(NAMESPACE)
	kubectl rollout status deployment/redis -n $(NAMESPACE)

# ── Canary ────────────────────────────────────────────────────────────────────

canary-10:
	kubectl apply -f k8s/istio/virtual-service-canary-10.yaml
	@echo "10% traffic now going to v2"

canary-50:
	kubectl apply -f k8s/istio/virtual-service-canary-50.yaml
	@echo "50% traffic now going to v2"

canary-100:
	kubectl apply -f k8s/istio/virtual-service-canary-100-v2.yaml
	@echo "100% traffic now on v2"

# ── Fault injection ───────────────────────────────────────────────────────────

fault-inject:
	kubectl apply -f k8s/istio/fault-injection.yaml
	@echo "50% of requests to backend will experience 5s delay"

fault-clear:
	kubectl apply -f k8s/istio/virtual-service-100-v1.yaml
	@echo "Fault cleared"

# ── Circuit breaker ───────────────────────────────────────────────────────────

circuit-breaker:
	kubectl apply -f k8s/istio/circuit-breaker.yaml
	@echo "Circuit breaker enabled — 3 consecutive 5xx errors ejects a backend pod for 30s"
	@echo "Trigger it: for i in \$$(seq 1 20); do curl -s localhost:8000/data; done"

circuit-breaker-clear:
	kubectl delete -f k8s/istio/circuit-breaker.yaml --ignore-not-found
	@echo "Circuit breaker removed"

# ── Retry policy ─────────────────────────────────────────────────────────────

retry:
	kubectl apply -f k8s/istio/retry-policy.yaml
	@echo "Retry policy enabled — up to 3 attempts, 5s per-try timeout"
	@echo "Combine with fault-inject to see retries absorbing failures"

retry-clear:
	kubectl apply -f k8s/istio/virtual-service-100-v1.yaml
	@echo "Retry policy cleared — back to plain virtual service"

# ── mTLS ─────────────────────────────────────────────────────────────────────

mtls-strict:
	kubectl apply -f k8s/istio/peer-authentication.yaml
	@echo "mTLS set to STRICT — plaintext connections rejected"

mtls-permissive:
	kubectl apply -f k8s/istio/peer-authentication-permissive.yaml
	@echo "mTLS set to PERMISSIVE — plaintext connections allowed (insecure)"

verify-mtls:
	kubectl exec -n $(NAMESPACE) deploy/frontend -c istio-proxy -- \
	  openssl s_client -connect backend:8001 2>&1 | grep -E "subject|issuer|Verify"

# ── AuthorizationPolicy ───────────────────────────────────────────────────────

authz-enable:
	kubectl apply -f k8s/istio/authorization-policy.yaml
	@echo "AuthorizationPolicy applied — only frontend can call backend"

authz-disable:
	kubectl delete -f k8s/istio/authorization-policy.yaml --ignore-not-found
	@echo "AuthorizationPolicy removed"

# ── Observability ─────────────────────────────────────────────────────────────

port-forward:
	kubectl port-forward -n $(NAMESPACE) svc/frontend 8000:8000

kiali:
	istioctl dashboard kiali

grafana:
	istioctl dashboard grafana

jaeger:
	istioctl dashboard jaeger

# ── Cleanup ───────────────────────────────────────────────────────────────────

clean:
	kubectl delete namespace $(NAMESPACE)
	minikube stop