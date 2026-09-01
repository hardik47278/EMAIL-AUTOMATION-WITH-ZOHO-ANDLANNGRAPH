from celery import Celery

celery = Celery(
    "email_pipeline",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0",
    include=["tasks"]
)


celery.conf.update(
    timezone="Asia/Kolkata",#sets local timezone
    enable_utc=True,#ensures that all times are stored in UTC in the backend
    task_serializer="json",#specefires task data witll be serialized using json
    result_serializer="json",#STORES DARTA IN JSON_FORMAT
    accept_content=["json"]
)


