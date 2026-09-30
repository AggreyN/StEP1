"""Email to the owner, through an SNS topic they are subscribed to.

The only module that talks to SNS. NOTIFY_TOPIC_ARN names the topic; empty
means nothing is sent and the event is only logged.

Sending never fails the request that caused it. The caller has already
committed whatever it is telling the owner about; this runs after the
response (a BackgroundTask), with short timeouts, and a failure is logged
and dropped.

What a person typed is untrusted. It goes only into the plain-text body,
quoted and capped. The subject, which mail clients show in lists and which
SNS limits to ASCII without line breaks, is built from the rating and a
cleaned, shortened name, never from the review itself.
"""

from __future__ import annotations

import logging
import unicodedata
from datetime import datetime

from app import config

log = logging.getLogger(__name__)

# SNS: "must be ASCII text that begins with a letter, number, or punctuation
# mark; must not include line breaks or control characters; and must be
# less than 100 characters long."
SUBJECT_MAX = 99
# How much of a name goes in a subject, and of a review in a body.
NAME_MAX = 60
BODY_TEXT_MAX = 2000


def _sns():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "sns",
        region_name=config.AWS_REGION,
        config=Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 2}),
    )


def ascii_line(text: str, most: int) -> str:
    """One line of plain ASCII: accents folded (e -> e), everything else
    that is not printable ASCII dropped, whitespace collapsed, cut to `most`."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    printable = "".join(ch if 32 <= ord(ch) < 127 else " " for ch in folded)
    line = " ".join(printable.split())
    return line[:most].rstrip()


def _plain(text: str, most: int) -> str:
    """Text for a plain-text body: control characters other than newlines and
    tabs removed, capped."""
    kept = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    return kept[:most]


def review_subject(rating: int, display_name: str | None, email: str) -> str:
    who = ascii_line(display_name or "", NAME_MAX) or ascii_line(email, NAME_MAX) or "someone"
    return ascii_line(f"StEP1 review: {int(rating)}/5 from {who}", SUBJECT_MAX)


def review_message(
    *, rating: int, body: str, email: str, display_name: str | None, created_at: datetime
) -> str:
    quoted = "\n".join(f"> {line}" for line in _plain(body, BODY_TEXT_MAX).splitlines())
    name = _plain(display_name or "", NAME_MAX).replace("\n", " ").strip()
    return (
        f"A new review of StEP1.\n"
        f"\n"
        f"Rating: {int(rating)}/5\n"
        f"From: {name + ' ' if name else ''}<{_plain(email, 320)}>\n"
        f"When: {created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        f"\n"
        f"{quoted}\n"
        f"\n"
        f"All reviews: {config.SITE_URL}/admin\n"
    )


def publish(subject: str, message: str) -> bool:
    """Send one email to the owner. True if SNS took it. Never raises."""
    if not config.NOTIFY_TOPIC_ARN:
        # The subject names a person; the log does not need to.
        log.info("notify: NOTIFY_TOPIC_ARN is empty; nothing sent")
        return False
    try:
        _sns().publish(TopicArn=config.NOTIFY_TOPIC_ARN, Subject=subject, Message=message)
    except Exception as exc:  # noqa: BLE001 - a lost email must not fail anything
        log.error("notify: could not publish to SNS: %s", type(exc).__name__)
        return False
    log.info("notify: sent")
    return True


def review_received(
    *, rating: int, body: str, email: str, display_name: str | None, created_at: datetime
) -> bool:
    return publish(
        review_subject(rating, display_name, email),
        review_message(
            rating=rating, body=body, email=email, display_name=display_name, created_at=created_at
        ),
    )
