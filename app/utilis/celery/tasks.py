from .config import celery_app
from app.utilis.Database import DataManager
from datetime import datetime, timezone


@celery_app.task
def save_post(url: str, expires_at: datetime, data: dict):
    database = DataManager()
    return database.add(url=url, expires_at=expires_at, data=data)


@celery_app.task
def get_post(url: str):
    database = DataManager()
    post = database.get(url)
    return post.to_dict() if post is not None else post


@celery_app.task
def delete_expired():
    database = DataManager()
    success = database.delete_expired()  # TODO: do smth in case of an error
