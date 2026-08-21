import hashlib
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
import yaml
from bs4 import BeautifulSoup


STATE_FILE = "state.json"
SOURCES_FILE = "sources.yml"

MAX_ITEMS_PER_SOURCE = 8
MAX_ITEMS_IN_ISSUE = 10

NOTIFY_USER = "glasirtorshavncollege-cmd"

MEANINGFUL_KEYWORDS = [
    "lóg", "lógar", "lógaruppskot", "kunngerð", "kunngerðir", "uppskot",
    "hoyring", "ummæli", "ummælis", "freist", "avgerð", "samtykt", "játtan",
    "fíggjarlóg", "ráðstevna", "strategi", "útbúgving", "skúli",
    "miðnám", "yrkis", "heilsu", "almanna", "bústað", "orka",
    "vinnu", "fiskivinnu", "trygd", "verja", "samstarv", "avtala",
    "skipan", "talgild", "vitlíki", "gransking", "stuðul", "verkætlan",
]

LOW_VALUE_KEYWORDS = [
    "vitjan", "móttøka", "heilsaði", "myndir", "røða", "setti",
    "luttók", "nevndarfundur",
    "fyrispurningar og svar",
    "spurningar og svar",
    "2014", "2015", "2016", "2017", "2018", "2019",
]

HEADERS = {
    "User-Agent": "fo-ministry-watch/1.0"
}


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"seen": []}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if "seen" not in data:
            data["seen"] = []

        return data
    except Exception:
        return {"seen": []}


def save_state(state):
    state["updated_at"] = datetime.now(timezone.utc).isoformat()

    # Keep state file reasonably small.
    state["seen"] = list(dict.fromkeys(state.get("seen", [])))[-1000:]

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_sources():
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or []

    if isinstance(data, dict):
        data = data.get("sources", [])

    sources = []

    for item in data:
        if not isinstance(item, dict):
            continue

        name = item.get("name") or item.get("title")
        url = item.get("url") or item.get("feed")

        if name and url:
            sources.append({
                "name": str(name),
                "url": str(url),
            })

    return sources


def item_id(url, title):
    base_text = (url or "") + "|" + (title or "")
    return hashlib.sha256(base_text.encode("utf-8")).hexdigest()


def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def fetch_html(url):
    response = requests.get(url, headers=HEADERS, timeout=20)
    response.raise_for_status()
    return response.text


def looks_like_old_archive_item(title, url):
    text = f"{title} {url}".lower()

    old_archive_patterns = [
        "fyrispurningar-og-svar-201",
        "fyrispurningar og svar 201",
        "spurningar-og-svar-201",
        "spurningar og svar 201",
    ]

    return any(pattern in text for pattern in old_archive_patterns)


def extract_items(source):
    html = fetch_html(source["url"])
    soup = BeautifulSoup(html, "html.parser")
    base_url = source["url"]

    candidates = []

    for a in soup.find_all("a", href=True):
        title = clean_text(a.get_text(" ", strip=True))

        if len(title) < 8:
            continue

        href = urljoin(base_url, a["href"])

        if href.startswith("mailto:") or href.startswith("tel:"):
            continue

        lower_href = href.lower()
        lower_title = title.lower()

        if looks_like_old_archive_item(title, href):
            continue

        # Avoid navigation/footer noise.
        if lower_title in ["les meira", "meira", "sí meira", "read more"]:
            continue

        looks_relevant = (
            "/tidindi" in lower_href
            or "/kunning" in lower_href
            or "/hoyring" in lower_href
            or "/ummali" in lower_href
            or "/ummæli" in lower_href
            or any(k in lower_title for k in MEANINGFUL_KEYWORDS)
        )

        if not looks_relevant:
            continue

        candidates.append({
            "source": source["name"],
            "title": title[:180],
            "url": href,
            "summary": "",
            "id": item_id(href, title),
        })

    # Deduplicate while preserving order.
    seen_urls = set()
    unique = []

    for item in candidates:
        key = item["url"]

        if key in seen_urls:
            continue

        seen_urls.add(key)
        unique.append(item)

    return unique[:MAX_ITEMS_PER_SOURCE]


def is_meaningful(item):
    text = f"{item.get('source', '')} {item.get('title', '')} {item.get('summary', '')} {item.get('url', '')}".lower()

    if looks_like_old_archive_item(item.get("title", ""), item.get("url", "")):
        return False

    if any(k in text for k in LOW_VALUE_KEYWORDS):
        return False

    if any(k in text for k in MEANINGFUL_KEYWORDS):
        return True

    return len(item.get("title", "")) >= 20


def make_summary(item):
    return item["title"]


def build_issue_body(items):
    lines = []

    lines.append("## Nýtt frá stjórnarráðunum")
    lines.append("")
    lines.append(f"@{NOTIFY_USER}")
    lines.append("")
    lines.append("Her er stuttur samandráttur av nýggjum almennum dagføringum frá stjórnarráðunum.")
    lines.append("")

    for i, item in enumerate(items, 1):
        lines.append(f"### {i}. {item['title']}")
        lines.append("")
        lines.append(f"**Kelda:** {item['source']}")
        lines.append("")
        lines.append(f"**Stuttur samandráttur:** {make_summary(item)}")
        lines.append("")
        lines.append(f"**Leinki:** {item['url']}")
        lines.append("")

    lines.append("---")
    lines.append(f"Automatiskt stovnað: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    return "\n".join(lines)


def create_github_issue(title, body):
    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN")

    if not repo:
        raise RuntimeError("Missing GITHUB_REPOSITORY")

    if not token:
        raise RuntimeError("Missing GITHUB_TOKEN")

    url = f"https://api.github.com/repos/{repo}/issues"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "fo-ministry-watch/1.0",
    }

    payload = {
        "title": title,
        "body": body,
        "assignees": [NOTIFY_USER],
    }

    response = requests.post(url, headers=headers, json=payload, timeout=20)

    # If assigning fails, create the issue anyway.
    if response.status_code == 422:
        print("WARNING: Could not assign issue. Retrying without assignee.")
        payload.pop("assignees", None)
        response = requests.post(url, headers=headers, json=payload, timeout=20)

    response.raise_for_status()

    return response.json().get("html_url")


def main():
    state = load_state()
    seen = set(state.get("seen", []))
    sources = load_sources()

    new_items = []

    for source in sources:
        try:
            items = extract_items(source)
        except Exception as e:
            print(f"WARNING: Could not fetch {source['name']}: {e}")
            continue

        for item in items:
            if item["id"] in seen:
                continue

            seen.add(item["id"])

            if is_meaningful(item):
                new_items.append(item)

    state["seen"] = list(seen)
    save_state(state)

    if not new_items:
        print("No meaningful new updates found.")
        return

    new_items = new_items[:MAX_ITEMS_IN_ISSUE]

    today = datetime.now().strftime("%d.%m.%Y")
    issue_title = f"Nýtt frá stjórnarráðunum - {today}"
    issue_body = build_issue_body(new_items)

    issue_url = create_github_issue(issue_title, issue_body)
    print(f"Created issue: {issue_url}")


if __name__ == "__main__":
    main()
