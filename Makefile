NAMESPACE=mesh-demo
FRONTEND_IMG=istio-mesh-demo/frontend:latest
BACKEND_IMG=istio-mesh-demo/backend:latest

.PHONY: all setup build deploy canary-10 canary-50 canary-100 fault-inject fault-clear verify-mtls port-forward kiali grafana clean authz-enable authz-disable

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
	kubectl apply -f k8s/base/frontend.yaml
	kubectl apply -f k8s/istio/peer-authentication.yaml
	kubectl apply -f k8s/istio/destination-rule.yaml
	kubectl apply -f k8s/istio/virtual-service-100-v1.yaml
	kubectl apply -f k8s/istio/authorization-policy.yaml
	kubectl rollout status deployment/frontend -n $(NAMESPACE)
	kubectl rollout status deployment/backend-v1 -n $(NAMESPACE)
	kubectl rollout status deployment/backend-v2 -n $(NAMESPACE)

canary-10:
	kubectl apply -f k8s/istio/virtual-service-canary-10.yaml
	@echo "10% traffic now going to v2"

canary-50:
	kubectl apply -f k8s/istio/virtual-service-canary-50.yaml
	@echo "50% traffic now going to v2"

canary-100:
	kubectl apply -f k8s/istio/virtual-service-canary-100-v2.yaml
	@echo "100% traffic now on v2"

fault-inject:
	kubectl apply -f k8s/istio/fault-injection.yaml
	@echo "50% of requests to backend will experience 5s delay"

fault-clear:
	kubectl apply -f k8s/istio/virtual-service-100-v1.yaml
	@echo "Fault cleared"

verify-mtls:
	kubectl exec -n $(NAMESPACE) deploy/frontend -c istio-proxy -- \
	  openssl s_client -connect backend:8001 2>&1 | grep -E "subject|issuer|Verify"

port-forward:
	kubectl port-forward -n $(NAMESPACE) svc/frontend 8000:8000

kiali:
	istioctl dashboard kiali

grafana:
	istioctl dashboard grafana

authz-enable:
	kubectl apply -f k8s/istio/authorization-policy.yaml
	@echo "AuthorizationPolicy applied — only frontend can call backend"

authz-disable:
	kubectl delete -f k8s/istio/authorization-policy.yaml
	@echo "AuthorizationPolicy removed"

clean:
	kubectl delete namespace $(NAMESPACE)
	minikube stop