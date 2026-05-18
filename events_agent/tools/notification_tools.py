"""
Notify the business owner via email or SMS for high-stakes decisions.
Used when autonomous agents need human approval.
"""

import config
from tools.email_tools import send_email


def notify_owner(subject: str, body: str, sms: bool = False) -> None:
    send_email(to=config.OWNER_EMAIL, subject=f"[Action Required] {subject}", body=body)

    if sms and config.TWILIO_ACCOUNT_SID and config.OWNER_PHONE:
        try:
            from twilio.rest import Client
            client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
            client.messages.create(
                body=f"Needham Events alert: {subject}\n\n{body[:200]}",
                from_=config.TWILIO_FROM_NUMBER,
                to=config.OWNER_PHONE,
            )
        except Exception as exc:
            print(f"SMS notification failed: {exc}")


def requires_owner_approval(description: str, cost_usd: float = 0) -> bool:
    """Return True if this action exceeds autonomous mode thresholds."""
    if not config.AUTONOMOUS_MODE:
        return True
    return cost_usd > config.HIGH_STAKES_THRESHOLD_USD
