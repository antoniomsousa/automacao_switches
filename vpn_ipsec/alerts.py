"""Alerts: always logged; also posted to a chat webhook (Slack/Teams/Google Chat accept {"text": ...}) when
ALERT_WEBHOOK_URL is set. The scripts also exit non-zero, so a scheduler or CI job flags the failure too."""
import logging
import os

import requests

log = logging.getLogger("vpn_ipsec")


def send_alert(title, details, session=None):
    lines = [title] + ["- %s" % d for d in details]
    log.error("\n".join(lines))
    url = os.environ.get("ALERT_WEBHOOK_URL")
    if not url:
        return False
    try:
        (session or requests).post(url, json={"text": "\n".join(lines)}, timeout=10).raise_for_status()
        return True
    except requests.RequestException:
        # A broken webhook must not hide the original failure
        log.exception("could not send the alert to the webhook")
        return False
