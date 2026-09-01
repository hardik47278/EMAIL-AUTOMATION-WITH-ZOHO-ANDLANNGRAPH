from google.oauth2.credentials import Credentials

TOKEN_PATH = "credentials/token.json"

creds = Credentials.from_authorized_user_file(TOKEN_PATH)

print("\nGranted Scopes:")
for scope in creds.scopes:
    print(scope)