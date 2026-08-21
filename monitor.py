import hashlib
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
import yaml
from bs4 import BeautifulSoup


STATE_FILE = "state.json"
SOURCES_FILE = "sources.yml"

MAX_ITEMS_PER_SOURCE = 6
MAX_ITEMS_IN_ISSUE = 8

HEADERS = {
    "User-Agent": "fo-ministry-watch/1.0"
}

MEANINGFUL_KEYWORDS = [
    "lóg", "lógar", "lógaruppskot", "kunngerð", "kunngerðir", "uppskot",
    "hoyring", "ummæli", "ummælis", "freist", "avgerð", "samtykt", "játtan",
    "fíggjarlóg", "ráðstevna", "strategi", "útbúgving", "skúli",
    "miðnám", "yrkis", "heilsu", "almanna", "bústað", "orka",
    "vinnu", "fiskivinnu", "trygd", "verja", "samstarv", "avtala",
    "skipan", "talgild", "vitlíki", "gransking", "stuðul", "verkætlan",
    "landsstýri", "ráð", "stjórnarráð", "undirskrivað", "sett í verk",
]

LOW_VALUE_TITLES = [
    "forsíða",
    "kunning",
    "arbeiðsøki",
    "um ráðið",
    "samband",
    "leys størv",
    "frágreiðingar og álit",
    "talgilding",
    "lógartænasta og lógarsmíð",
    "rundskriv um lógarsmíð",
    "uppskot til ummælis",
    "kunngerðing o.tíl.",
    "almanna- og bústaðamálaráðið",
    "heilsu- og orkumálaráðið",
    "vinnumálaráðið",
]

LOW_VALUE_KEYWORDS = [
    "vitjan",
    "móttøka",
    "heilsaði",
    "myndir",
    "nevndarfundur",
    "fyrispurningar og svar",
    "spurningar og svar",
]


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


def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def item_id(url, title):
    base_text = (url or "") + "|" + (title or "")
    return hashlib.sha256(base_text.encode("utf-8")).hexdigest()


def fetch_html(url):
    response = requests.get(url, headers=HEADERS, timeout=20)
    response.raise_for_status()
    return response.text


def normalize_url(url):
    parsed = urlparse(url)
    return parsed.scheme + "://" + parsed.netloc + parsed.path.rstrip("/") + "/"


def is_same_url(a, b):
    return normalize_url(a) == normalize_url(b)


def is_low_value_title(title):
    title_lower = clean_text(title).lower()
    return title_lower in LOW_VALUE_TITLES


def looks_like_old_archive_item(title, url):
    text = f"{title} {url}".lower()

    old_archive_patterns = [
        "fyrispurningar-og-svar-201",
        "fyrispurningar og svar 201",
        "spurningar-og-svar-201",
        "spurningar og svar 201",
        "/2014/",
        "/2015/",
        "/2016/",
        "/2017/",
        "/2018/",
        "/2019/",
    ]

    return any(pattern in text for pattern in old_archive_patterns)


def is_probable_news_url(source_url, href):
    source_lower = source_url.lower()
    href_lower = href.lower()

    if is_same_url(source_url, href):
        return False

    if "hoyringar" in source_lower:
        return (
            "/hoyringar/" in href_lower
            and not is_same_url(source_url, href)
        )

    return (
        "/fo/kunning/tidindi/" in href_lower
        and not is_same_url(source_url, href)
    )


def extract_page_title(soup, fallback):
    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.get("content"):
        title = clean_text(og_title.get("content"))
        if title:
            return title

    h1 = soup.find("h1")
    if h1:
        title = clean_text(h1.get_text(" ", strip=True))
        if title:
            return title

    return fallback


def extract_description_from_page(url):
    try:
        html = fetch_html(url)
        soup = BeautifulSoup(html, "html.parser")

        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            text = clean_text(meta.get("content"))
            if len(text) >= 40:
                return text[:500]

        og = soup.find("meta", attrs={"property": "og:description"})
        if og and og.get("content"):
            text = clean_text(og.get("content"))
            if len(text) >= 40:
                return text[:500]

        paragraphs = []

        for p in soup.find_all("p"):
            text = clean_text(p.get_text(" ", strip=True))

            if len(text) < 60:
                continue

            lower = text.lower()

            skip_phrases = [
                "cookies",
                "far til innihald",
                "les meira",
                "deil",
                "facebook",
                "linkedin",
                "twitter",
                "teldupost",
                "©",
            ]

            if any(skip in lower for skip in skip_phrases):
                continue

            paragraphs.append(text)

        if paragraphs:
            return paragraphs[0][:500]

    except Exception:
        return ""

    return ""


def extract_items(source):
    html = fetch_html(source["url"])
    soup = BeautifulSoup(html, "html.parser")
    base_url = source["url"]

    candidates = []

    for a in soup.find_all("a", href=True):
        raw_title = clean_text(a.get_text(" ", strip=True))

        if len(raw_title) < 8:
            continue

        href = urljoin(base_url, a["href"])

        if href.startswith("mailto:") or href.startswith("tel:"):
            continue

        if not is_probable_news_url(source["url"], href):
            continue

        if is_low_value_title(raw_title):
            continue

        if looks_like_old_archive_item(raw_title, href):
            continue

        candidates.append({
            "source": source["name"],
            "title": raw_title[:180],
            "url": href,
            "summary": "",
            "id": item_id(href, raw_title),
        })

    seen_urls = set()
    unique = []

    for item in candidates:
        key = normalize_url(item["url"])

        if key in seen_urls:
            continue

        seen_urls.add(key)
        unique.append(item)

    return unique[:MAX_ITEMS_PER_SOURCE]


def is_meaningful(item):
    text = f"{item.get('source', '')} {item.get('title', '')} {item.get('summary', '')} {item.get('url', '')}".lower()

    if is_low_value_title(item.get("title", "")):
        return False

    if looks_like_old_archive_item(item.get("title", ""), item.get("url", "")):
        return False

    if any(k in text for k in LOW_VALUE_KEYWORDS):
        return False

    # Tá URL’in er ein verulig tíðinda-/hoyringarsíða, taka vit hana við,
    # hóast heitið ikki altíð inniheldur sterkt politiskt lyklaorð.
    return True


def enrich_items(items):
    enriched = []

    for item in items:
        item = dict(item)

        try:
            html = fetch_html(item["url"])
            soup = BeautifulSoup(html, "html.parser")
            item["title"] = extract_page_title(soup, item["title"])
        except Exception:
            pass

        item["summary"] = extract_description_from_page(item["url"])

        if not item["summary"]:
            item["summary"] = item["title"]

        enriched.append(item)

    return enriched


def make_summary(item):
    summary = clean_text(item.get("summary", ""))

    if not summary:
        return item["title"]

    if summary == item["title"]:
        return item["title"]

    return summary


def build_issue_body(items):
    lines = []

    lines.append("## Nýtt frá stjórnarráðunum")
    lines.append("")
    lines.append("Her er stuttur samandráttur av nýggjum almennum dagføringum frá stjórnarráðunum.")
    lines.append("")

    for i, item in enumerate(items, 1):
        lines.append(f"### {i}. {item['title']}")
        lines.append("")
        lines.append(f"**Kelda:** {item['source']}")
        lines.append("")
        lines.append("**Samandráttur:**")
        lines.append("")
        lines.append(make_summary(item))
        lines.append("")
        lines.append(f"**Les meira:** {item['url']}")
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

    payload = {
        "title": title,
        "body": body,
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "fo-ministry-watch/1.0",
    }

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
    new_items = enrich_items(new_items)

    today = datetime.now().strftime("%d.%m.%Y")
    issue_title = f"Nýtt frá stjórnarráðunum - {today}"
    issue_body = build_issue_body(new_items)

    issue_url = create_github_issue(issue_title, issue_body)
    print(f"Created issue: {issue_url}")


if __name__ == "__main__":
    main()
