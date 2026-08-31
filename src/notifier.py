from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from jinja2 import Environment, FileSystemLoader

from src.config import Config, TEMPLATES_DIR
from src.models import Listing

logger = logging.getLogger(__name__)


def send_notification(new_listings: list[Listing], config: Config):
    if not config.notifications.enabled:
        logger.info("Notifications disabled")
        return

    if not config.gmail_app_password:
        logger.warning("No Gmail app password configured, skipping email notification")
        _log_notification(new_listings)
        return

    if not config.notifications.recipients:
        logger.warning("No notification recipients configured")
        return

    sorted_listings = sorted(new_listings, key=lambda l: l.score or 0, reverse=True)
    top_listings = sorted_listings[:5]

    html = _render_email(top_listings, len(new_listings), config)
    today = datetime.now(timezone.utc).strftime("%b %d, %Y")
    subject = f"[Apartment Hunt] {len(new_listings)} new listing{'s' if len(new_listings) != 1 else ''} - {today}"
    sender = config.notifications.from_email

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender, config.gmail_app_password)
            for recipient in config.notifications.recipients:
                msg = MIMEMultipart("alternative")
                msg["From"] = sender
                msg["To"] = recipient
                msg["Subject"] = subject
                msg.attach(MIMEText(html, "html"))
                server.sendmail(sender, recipient, msg.as_string())
        logger.info(f"Email sent to {len(config.notifications.recipients)} recipients via Gmail SMTP")
    except Exception as e:
        logger.error(f"Failed to send email via Gmail SMTP: {e}")
        _log_notification(new_listings)


def _render_email(top_listings: list[Listing], total_count: int, config: Config) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("email.html")
    return template.render(
        listings=top_listings,
        total_count=total_count,
        dashboard_url=config.site.base_url,
        date=datetime.now(timezone.utc).strftime("%B %d, %Y"),
    )


def _log_notification(listings: list[Listing]):
    logger.info(f"Would notify about {len(listings)} new listings:")
    for l in listings[:5]:
        logger.info(f"  - {l.address} | ${l.price}/mo | {l.bedrooms}bd/{l.bathrooms}ba | Score: {l.score}")
