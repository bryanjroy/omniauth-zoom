"""
One-time OAuth2 setup for Gmail and Google Calendar.
Run this interactively before starting the agent system.

Prerequisites:
  1. Create a GCP project at console.cloud.google.com
  2. Enable Gmail API and Google Calendar API
  3. Create OAuth2 credentials (Desktop App)
  4. Download the JSON and save to events_agent/credentials/gmail_credentials.json
  5. Run: python setup_auth.py
"""

from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
import config

SCOPES = config.GMAIL_SCOPES + config.GCAL_SCOPES

def main():
    creds_path = config.GMAIL_CREDENTIALS_FILE
    if not creds_path.exists():
        print(f"ERROR: credentials file not found at {creds_path}")
        print("Download OAuth2 credentials from GCP Console and save there.")
        return

    print("Opening browser for Google OAuth2 authorization...")
    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
    creds = flow.run_local_server(port=0)

    # Save Gmail token
    gmail_token = config.GMAIL_TOKEN_FILE
    gmail_token.parent.mkdir(parents=True, exist_ok=True)
    gmail_token.write_text(creds.to_json())
    print(f"Gmail token saved to {gmail_token}")

    # Save Calendar token (same credentials)
    gcal_token = config.BASE_DIR / "credentials" / "gcal_token.json"
    gcal_token.write_text(creds.to_json())
    print(f"Calendar token saved to {gcal_token}")

    print("\nAuth setup complete! You can now run: python main.py setup")


if __name__ == "__main__":
    main()
