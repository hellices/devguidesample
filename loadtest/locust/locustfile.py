"""
Locust load test targeting Azure Application Gateway → AKS backend.

Execution options:
  1. Azure Load Testing (recommended):
     az load test create --load-test-resource <ALT_NAME> -g <RG> --test-id appgw-test \
       --test-type Locust --test-plan locustfile.py
     az load test-run create --load-test-resource <ALT_NAME> -g <RG> --test-id appgw-test \
       --test-run-id run1 \
       --env LOCUST_HOST=http://<APPGW_IP> LOCUST_USERS=200 LOCUST_SPAWN_RATE=20 LOCUST_RUN_TIME=5m

  2. Local execution (for debugging):
     locust -f locustfile.py --host http://<appgw-ip>
"""

import os
from locust import HttpUser, task, between, tag


class AppGWUser(HttpUser):
    """Simulates user traffic through Application Gateway to AKS backend."""

    wait_time = between(1, 3)

    @tag("health")
    @task(1)
    def health_check(self):
        """GET /health - lightweight health probe."""
        with self.client.get("/health", catch_response=True) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Health check failed: {resp.status_code}")

    @tag("api")
    @task(5)
    def get_items(self):
        """GET /api/items - typical read operation."""
        self.client.get("/api/items")

    @tag("api")
    @task(3)
    def get_item_by_id(self):
        """GET /api/items/:id - single item lookup."""
        self.client.get("/api/items/1")

    @tag("api")
    @task(2)
    def create_item(self):
        """POST /api/items - write operation."""
        payload = {"name": "load-test-item", "value": "test"}
        self.client.post("/api/items", json=payload)

    @tag("static")
    @task(1)
    def get_root(self):
        """GET / - root page."""
        self.client.get("/")
