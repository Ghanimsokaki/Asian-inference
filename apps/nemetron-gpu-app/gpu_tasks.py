"""Put your app-side GPU workloads here."""
from __future__ import annotations

import subprocess
from typing import Any


def gpu_status() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=False,
        )
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return {"available": bool(lines), "devices": lines}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": str(exc)}


def run_gpu_app_task(task: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    task = (task or "").strip().lower()
    if task == "gpu_status":
        return gpu_status()
    return {
        "task": task,
        "payload": payload,
        "message": (
            "Replace `run_gpu_app_task()` with your real GPU app logic, such as vision, "
            "audio, embeddings, local inference, or another cloud app workload."
        ),
    }
