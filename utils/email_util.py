import os
import re
import logging
import smtplib
from dotenv import load_dotenv
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

load_dotenv()

logger = logging.getLogger(__name__)

SMTP_USER = os.getenv('SMTP_USER')
SMTP_SERVER = os.getenv('SMTP_SERVER')
SMTP_PORT = os.getenv('SMTP_PORT')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')

SMTP_TIMEOUT = 20  # seconds — without this a stalled SMTP server hangs the request

# Gmail shows app passwords as 4 groups of 4 ("abcd efgh ijkl mnop"); those
# spaces are display-only and must not be sent to the server.
_APP_PASSWORD_WITH_SPACES = re.compile(r'^([a-z]{4} ){3}[a-z]{4}$', re.IGNORECASE)


def _smtp_port():
    """`SMTP_PORT` arrives from the environment as a string."""
    try:
        return int(SMTP_PORT)
    except (TypeError, ValueError):
        return None


def _smtp_password():
    if SMTP_PASSWORD and _APP_PASSWORD_WITH_SPACES.match(SMTP_PASSWORD):
        return SMTP_PASSWORD.replace(' ', '')
    return SMTP_PASSWORD


def _missing_settings():
    missing = [
        name for name, value in (
            ('SMTP_SERVER', SMTP_SERVER),
            ('SMTP_PORT', SMTP_PORT),
            ('SMTP_USER', SMTP_USER),
            ('SMTP_PASSWORD', SMTP_PASSWORD),
        ) if not value
    ]
    if SMTP_PORT and _smtp_port() is None:
        missing.append('SMTP_PORT (not a number)')
    return missing


def send_email(subject: str, recipient: str, html_content: str, text_content: str = None) -> bool:
    """Send one HTML mail. Returns True on success, False on any failure.

    Callers that depend on the mail actually arriving (OTP delivery) MUST check
    the return value. Failures used to be swallowed and printed, which is why
    the API could answer 200 while nothing was ever sent.
    """
    missing = _missing_settings()
    if missing:
        logger.error("Cannot send email to %s — missing SMTP settings: %s", recipient, ', '.join(missing))
        return False

    if not recipient:
        logger.error("Cannot send email '%s' — no recipient address.", subject)
        return False

    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = SMTP_USER
        msg['To'] = recipient
        msg['Subject'] = subject

        if text_content:
            msg.attach(MIMEText(text_content, 'plain'))
        msg.attach(MIMEText(html_content, 'html'))

        port = _smtp_port()
        # Port 465 is implicit TLS (SMTPS); 587 and 25 negotiate with STARTTLS.
        if port == 465:
            with smtplib.SMTP_SSL(SMTP_SERVER, port, timeout=SMTP_TIMEOUT) as server:
                server.login(SMTP_USER, _smtp_password())
                server.sendmail(SMTP_USER, recipient, msg.as_string())
        else:
            with smtplib.SMTP(SMTP_SERVER, port, timeout=SMTP_TIMEOUT) as server:
                server.starttls()
                server.login(SMTP_USER, _smtp_password())
                server.sendmail(SMTP_USER, recipient, msg.as_string())

        logger.info("Email '%s' sent to %s", subject, recipient)
        return True

    except smtplib.SMTPAuthenticationError as e:
        # By far the most common cause: an expired/revoked Gmail app password,
        # or 2-Step Verification turned off on the sending account.
        logger.error(
            "SMTP authentication failed on %s as %s — check SMTP_PASSWORD "
            "(Gmail needs an App Password, not the account password): %s",
            SMTP_SERVER, SMTP_USER, e
        )
        return False
    except Exception as e:
        logger.exception("Failed to send email '%s' to %s: %s", subject, recipient, e)
        return False
