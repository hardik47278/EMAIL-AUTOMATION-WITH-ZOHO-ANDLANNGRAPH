import os
from dotenv import load_dotenv
load_dotenv()

from langsmith import Client

client = Client(
    api_url="https://aws.api.smith.langchain.com",
    api_key=os.getenv("LANGCHAIN_API_KEY")
)

runs = client.list_runs(
    project_name="WORKMATES",
    run_type="chain",
    limit=10
)

for run in runs:
    print("Name      :", run.name)
    print("Latency   :", run.latency)
    print("Tokens    :", run.total_tokens)
    print("Error     :", run.error)
    print("Trace URL :", run.url)
    print("---")