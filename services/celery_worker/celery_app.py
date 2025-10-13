from celery import Celery
import os

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
celery = Celery(
    "tasks",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

import .tasks
#celery.conf.task_routes = {"logai.tasks.*": {"queue": "llama"}}