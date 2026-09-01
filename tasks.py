from celery_app import celery
from mainn import run_pipeline

@celery.task(bind=True,max_retries=3)
def fetch_and_process(self):
    try:
        run_pipeline()
    except Exception as e:
        print(f"Task failed:{e}")
        self.retry(countdown=60)



