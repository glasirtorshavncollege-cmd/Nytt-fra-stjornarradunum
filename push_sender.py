"""Optional GitHub-only Web Push sender. No secrets are stored in Pages or repository."""
import argparse
import json
import os
import subprocess
from pathlib import Path


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def newly_published():
    current = load_json("docs/feed.json")
    try:
        previous = json.loads(subprocess.check_output(
            ["git", "show", "HEAD^:docs/feed.json"], text=True))
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return []  # Never send mass backfill after a missing baseline.
    known = {x.get("url") for x in previous if isinstance(x, dict)}
    return [x for x in current if isinstance(x, dict) and x.get("url") not in known]


def send(items):
    if os.environ.get("PUSH_ENABLED", "").lower() != "true":
        print("Push disabled: set PUSH_ENABLED=true after setup")
        return
    private = os.environ.get("PUSH_VAPID_PRIVATE_KEY", "")
    subscriptions_json = os.environ.get("PUSH_SUBSCRIPTIONS_JSON", "")
    contact = os.environ.get("PUSH_VAPID_CONTACT", "")
    if not private or not subscriptions_json or not contact:
        print("Push setup incomplete; no notification sent")
        return
    from pywebpush import webpush, WebPushException
    subscriptions = json.loads(subscriptions_json)
    if not isinstance(subscriptions, list):
        raise ValueError("PUSH_SUBSCRIPTIONS_JSON must be a JSON list")
    if not items:
        print("No new items; no push")
        return
    newest = items[0]
    message = {
        "title": "Nýtt frá ráðunum",
        "body": (newest.get("title", "Nýggj tíðindi") if len(items) == 1 else f"{len(items)} nýggj tíðindi í appini"),
        "articleId": newest.get("id", ""),
    }
    success = 0
    for subscription in subscriptions:
        try:
            webpush(subscription_info=subscription, data=json.dumps(message, ensure_ascii=False),
                    vapid_private_key=private, vapid_claims={"sub": contact}, ttl=3600, timeout=15)
            success += 1
    except WebPushException as error:
    status = getattr(error.response, "status_code", "?")
    print(f"Push delivery failed (HTTP {status})")
    print(f"Error details: {str(error)[:500]}")    
        except Exception as error:
            print(f"Push delivery failed: {type(error).__name__}")
    print(f"Push sent to {success}/{len(subscriptions)} subscription(s)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Explicit test notification")
    args = parser.parse_args()
    if args.test:
        send([{"id":"", "title":"Hetta er ein royndarfráboðan frá Ministry Check"}])
    else:
        send(newly_published())
