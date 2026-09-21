"""Modal cloud GPU worker for app-side GPU tasks."""
from __future__ import annotations

import os

import modal

from gpu_tasks import run_gpu_app_task

APP_NAME = os.getenv("APP_NAME", "nemetron-cloud-app")
GPU_TYPE = os.getenv("MODAL_GPU", "T4")

image = modal.Image.debian_slim().pip_install_from_requirements("requirements.txt")
app = modal.App(APP_NAME)


@app.function(image=image, gpu=GPU_TYPE, timeout=3600)
def run_cloud_gpu_task(task: str, payload: dict | None = None) -> dict:
    return {
        "app": APP_NAME,
        "gpu": GPU_TYPE,
        "result": run_gpu_app_task(task, payload),
    }


@app.local_entrypoint()
def main(task: str = "gpu_status"):
    print(run_cloud_gpu_task.remote(task, {}))
