from tasks import fetch_and_process

result = fetch_and_process.delay()
print(f"Task sent! ID: {result.id}")