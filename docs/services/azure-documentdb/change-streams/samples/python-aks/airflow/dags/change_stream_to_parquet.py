"""Export Azure DocumentDB change stream events to Parquet in ADLS Gen2.

Each run starts one pod in the ``cslab`` namespace. The pod resumes from the
checkpoint in the lake, writes the events recorded before the run started and
exits. ``max_active_runs=1`` keeps a single reader per stream.

Trigger with ``{"fault_after_chunks": N}`` to make the first try exit after the
Nth upload and before the checkpoint, then let the retry finish the run.
"""

import os
from datetime import datetime, timedelta

from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from airflow.providers.cncf.kubernetes.secret import Secret
from airflow.sdk import DAG
from kubernetes.client import models as k8s

INTERVAL = timedelta(minutes=int(os.getenv("CS_EXPORT_INTERVAL_MIN", "5")))

with DAG(
    dag_id="change_stream_to_parquet",
    schedule=INTERVAL,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 3, "retry_delay": timedelta(seconds=30)},
    tags=["change-stream"],
):
    KubernetesPodOperator(
        task_id="export",
        name="cs-lake-export",
        namespace="cslab",
        image=os.getenv("CS_EXPORT_IMAGE", "cslab:latest"),
        cmds=["python", "lake_export.py"],
        env_vars={
            "LAKE_URL": os.getenv("CS_LAKE_URL", ""),
            "LAKE_FILESYSTEM": "cdc",
            "LAKE_PREFIX": "orders",
            "STREAM_ID": "orders",
            "CHUNK_EVENTS": os.getenv("CS_CHUNK_EVENTS", "100000"),
            "MAX_EVENTS": "{{ dag_run.conf.get('max_events', 0) }}",
            "FAULT_EXIT_AFTER_UPLOAD":
                "{{ dag_run.conf.get('fault_after_chunks', 0) if ti.try_number == 1 else 0 }}",
        },
        secrets=[Secret("env", "MONGO_URI", "docdb", "uri")],
        service_account_name="cs-lake",
        labels={"azure.workload.identity/use": "true"},
        container_resources=k8s.V1ResourceRequirements(
            requests={"cpu": "1", "memory": "1Gi"}, limits={"memory": "4Gi"}),
        get_logs=True,
        startup_timeout_seconds=300,
        on_finish_action="delete_succeeded_pod",
    )
