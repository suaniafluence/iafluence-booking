"""One-time OAuth consent for the IAfluence Gmail account.

Usage (on a machine with a browser):
    uv run python -m scripts.google_oauth_init path/to/client_secret.json

Prints GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN for the .env file.
The OAuth consent screen must be "In production", otherwise the refresh token expires after 7 days.
"""

import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

from app.services.google_client import SCOPES


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    secrets_file = sys.argv[1]
    flow = InstalledAppFlow.from_client_secrets_file(secrets_file, SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    with open(secrets_file, encoding="utf-8") as fh:
        client = next(iter(json.load(fh).values()))
    print("\nAdd to your .env:\n")
    print(f"GOOGLE_CLIENT_ID={client['client_id']}")
    print(f"GOOGLE_CLIENT_SECRET={client['client_secret']}")
    print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")


if __name__ == "__main__":
    main()
