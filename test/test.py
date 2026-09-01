import json

with open("test/sample_email.json", "r") as f:
    email = json.load(f)

print("SUBJECT:", email["subject"])
print("FROM:", email["from"])
print("BODY:", email["body"])