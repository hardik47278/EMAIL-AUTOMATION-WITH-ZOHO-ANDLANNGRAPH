import sys
import os
from datetime import datetime

class Logger:
    def __init__(self, file):
        self.file = file

    def write(self, msg):
        self.file.write(msg)
        self.file.flush()

    def flush(self):
        self.file.flush()


def setup_logger():
    os.makedirs("logs", exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_path = f"logs/run_{timestamp}.log"

    log_file = open(log_path, "a", encoding="utf-8")

    sys.stdout = Logger(log_file)
    sys.stderr = Logger(log_file)

    print(f"[LOGGER STARTED] Saving logs to {log_path}")

setup_logger()

print("Hello from stdout")

raise Exception("This is an error")