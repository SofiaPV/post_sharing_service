from celery import Celery
from kombu import Queue
from celery.schedules import crontab

celery_app = Celery("celery",
                    broker='redis://localhost:6379/0',
                    backend='redis://localhost:6379/1',
                    include=["app.utilis.celery.tasks"])

# create queues for different tasks
celery_app.conf.task_queues = (
    Queue("high"),  # for giving post by url (id)
    Queue("normal"),  # for saving new posts
    Queue("low")  # for deleting expired posts
)

# Task routes: where to find tasks and where to put them
CELERY_TASK_ROUTES = {
    "app.utilis.celery.tasks.get_post": {"queue": "high"},
    "app.utilis.celery.tasks.save_post": {"queue": "normal"},
    "app.utilis.celery.tasks.delete_expired": {"queue": "low"}
}

celery_app.conf.task_default_queue = "normal"
celery_app.conf.task_routes = CELERY_TASK_ROUTES

# add periodic post deletion
celery_app.conf.beat_schedule = {
    "delete_expired": {  # delete expired posts (name)
        "task": "app.utilis.celery.tasks.delete_expired",
        "schedule": crontab(minute="*/5", hour='*'),
    }
}
