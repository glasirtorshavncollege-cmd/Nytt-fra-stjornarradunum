
"""GitHub-only Web Push sender for Nýtt frá ráðunum.

Sends push notifications only for newly added feed items
that satisfy the freshness rules.

No secrets are stored in GitHub Pages or repository files.
"""

import argparse
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse


MAX_AGE_HOURS = 48


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def normalize_url(url):
    if not isinstance(url, str) or not url.strip():
        return ""

    parsed = urlparse(url.strip())
    path = parsed.path or "/"

    if path != "/" and path.endswith("/"):
        path = path[:-1]

    return urlunparse((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        path,
        "",
        parsed.query,
        "",
    ))


def parse_timestamp(value):
    if not isinstance(value, str) or not value.strip():
        return None

    try:
        parsed = datetime.fromisoformat(
            value.strip().replace("Z", "+00:00")
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc)

    except ValueError:
        return None


def is_recent_article(item, now):
    """Check whether a newly published feed item can trigger push.

    Publication dates contain only a calendar date, so today
    and yesterday are accepted conservatively.

    If publication date is unknown, use discovery timestamp
    as a fallback. This does not prove actual article age.
    """

    published = item.get("published_at")

    if published:
        try:
            published_day = datetime.strptime(
                published[:10], "%Y-%m-%d"
            ).date()
        except (ValueError, TypeError):
            print("Push skipped: invalid publication date")
            return False

        today = now.date()
        yesterday = today - timedelta(days=1)

        if yesterday <= published_day <= today:
            return True

        print(
            f"Push skipped: publication date outside "
            f"48-hour window ({published_day})"
        )
        return False

    found_at = parse_timestamp(item.get("found_at"))

    if found_at is None:
        print("Push skipped: missing valid discovery date")
        return False

    age = now - found_at

    if timedelta(0) <= age <= timedelta(hours=MAX_AGE_HOURS):
        return True

    print("Push skipped: discovery date outside 48-hour window")
    return False


def newly_published():
    """Return only newly added, recent articles.

    Compare current feed to the feed in the previous commit.
    Never send a mass backfill if the baseline is missing.
    """

    current = load_json("docs/feed.json")

    if not isinstance(current, list):
        raise ValueError("docs/feed.json must contain a JSON list")

    try:
        previous = json.loads(
            subprocess.check_output(
                ["git", "show", "HEAD^:docs/feed.json"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
        )

    except (
        subprocess.CalledProcessError,
        json.JSONDecodeError,
    ):
        print("Previous feed unavailable; no push")
        return []

    if not isinstance(previous, list):
        print("Previous feed invalid; no push")
        return []

    known_urls = {
        normalize_url(article.get("url"))
        for article in previous
        if isinstance(article, dict)
    }

    now = datetime.now(timezone.utc)

    new_items = []
    new_urls = set()

    for item in current:
        if not isinstance(item, dict):
            continue

        url = normalize_url(item.get("url"))

        if not url:
            continue

        if url in known_urls or url in new_urls:
            continue

        new_urls.add(url)

        if is_recent_article(item, now):
            new_items.append(item)

    print(f"New eligible push articles: {len(new_items)}")

    return new_items


def send(items):
    if os.environ.get("PUSH_ENABLED", "").strip().lower() != "true":
        print("Push disabled: set PUSH_ENABLED=true after setup")
        return

    private = os.environ.get(
        "PUSH_VAPID_PRIVATE_KEY", ""
    ).strip()

    subscriptions_json = os.environ.get(
        "PUSH_SUBSCRIPTIONS_JSON", ""
    )

    contact = os.environ.get(
        "PUSH_VAPID_CONTACT", ""
    ).strip()

    if not private or not subscriptions_json or not contact:
        print("Push setup incomplete; no notification sent")
        return

    if not items:
        print("No eligible new articles; no push")
        return

    from pywebpush import webpush, WebPushException

    subscriptions = json.loads(subscriptions_json)

    if not isinstance(subscriptions, list):
        raise ValueError(
            "PUSH_SUBSCRIPTIONS_JSON must be a JSON list"
        )

    if not subscriptions:
        print("No subscriptions configured")
        return

    newest = items[0]

    message = {
        "title": "Nýtt frá ráðunum",
        "body": (
            newest.get("title", "Nýggj tíðindi")
            if len(items) == 1
            else f"{len(items)} nýggj tíðindi í appini"
        ),
        "articleId": newest.get("id", ""),
    }

    success = 0

    for subscription in subscriptions:
        try:
            webpush(
                subscription_info=subscription,
                data=json.dumps(
                    message,
                    ensure_ascii=False,
                ),
                vapid_private_key=private,
                vapid_claims={"sub": contact},
                ttl=3600,
                timeout=15,
            )

            success += 1

        except WebPushException as error:
            status = getattr(
                error.response,
                "status_code",
                "?",
            )

            print(f"Push delivery failed (HTTP {status})")

            # Avoid exposing subscription details in logs.
            reason = getattr(error.response, "reason", "")
            if reason:
                print(f"Push service reason: {reason}")

        except Exception as error:
            print(
                f"Push delivery failed: "
                f"{type(error).__name__}"
            )

    print(
        f"Push sent to "
        f"{success}/{len(subscriptions)} subscription(s)"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--test",
        action="store_true",
        help="Send an explicit test notification",
    )

    args = parser.parse_args()

    if args.test:
        send([
            {
                "id": "",
                "title": (
                    "Hetta er ein royndarfráboðan "
                    "frá Ministry Check"
                ),
            }
        ])
    else:
        send(newly_published())
