#!/bin/bash
# Deploy AI Foundry Chat API to AKS with Pyroscope profiling

set -e

NAMESPACE="ai-foundry-chat"
APP_NAME="ai-foundry-chat"

echo "=== Creating namespace ==="
kubectl create namespace $NAMESPACE 2>/dev/null || true

echo "=== Creating ConfigMap with app.py ==="
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
kubectl create configmap chat-app \
  --from-file="$SCRIPT_DIR/app.py" \
  -n $NAMESPACE \
  --dry-run=client -o yaml | kubectl apply -f -

echo "=== Creating Deployment ==="
cat << 'EOF' | kubectl apply -f -
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ai-foundry-chat
  namespace: ai-foundry-chat
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ai-foundry-chat
  namespace: ai-foundry-chat
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ai-foundry-chat
  template:
    metadata:
      labels:
        app: ai-foundry-chat
      annotations:
        profiles.grafana.com/cpu.scrape: "true"
        profiles.grafana.com/cpu.port: "8080"
        profiles.grafana.com/memory.scrape: "true"
        profiles.grafana.com/memory.port: "8080"
    spec:
      serviceAccountName: ai-foundry-chat
      containers:
      - name: chat-api
        image: python:3.11-slim
        imagePullPolicy: IfNotPresent
        workingDir: /app
        command:
        - sh
        - -c
        - |
          pip install --no-cache-dir \
            fastapi uvicorn[standard] pydantic \
            pyroscope-io \
            azure-ai-inference azure-identity azure-core \
            aiohttp
          python app.py
        
        ports:
        - name: http
          containerPort: 8080
        
        env:
        - name: PYROSCOPE_SERVER
          value: "http://pyroscope.observability.svc.cluster.local.:4040"
        - name: PYROSCOPE_SAMPLE_RATE
          value: "100"
        
        livenessProbe:
          httpGet:
            path: /health
            port: http
          initialDelaySeconds: 30
          periodSeconds: 30
        
        readinessProbe:
          httpGet:
            path: /health
            port: http
          initialDelaySeconds: 10
          periodSeconds: 10
        
        resources:
          requests:
            cpu: 200m
            memory: 512Mi
          limits:
            cpu: 1000m
            memory: 1Gi
        
        volumeMounts:
        - name: app-code
          mountPath: /app
      
      volumes:
      - name: app-code
        configMap:
          name: chat-app
          defaultMode: 0755
---
apiVersion: v1
kind: Service
metadata:
  name: ai-foundry-chat
  namespace: ai-foundry-chat
spec:
  type: ClusterIP
  selector:
    app: ai-foundry-chat
  ports:
  - name: http
    port: 8080
    targetPort: http
EOF

echo "=== Waiting for deployment ==="
kubectl rollout status deployment/ai-foundry-chat -n $NAMESPACE --timeout=2m

echo ""
echo "=== Deployment Complete ==="
kubectl get pods -n $NAMESPACE
echo ""
echo "✅ API deployed successfully!"
echo ""
echo "Next steps:"
echo "1. Port forward the API:"
echo "   kubectl port-forward -n $NAMESPACE svc/$APP_NAME 8080:8080"
echo ""
echo "2. In another terminal, run the test:"
echo "   python /Users/hwang-inhwan/workspace/devguidesample/aifoundry/chat-profiling-test/test.py --url http://localhost:8080 --requests 20"
echo ""
echo "3. View profiles in Pyroscope:"
echo "   kubectl port-forward -n observability svc/pyroscope 4040:4040"
echo "   Open http://localhost:4040 and select 'ai-foundry-chat' service"
