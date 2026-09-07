import hashlib
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, urlunparse

import requests
import yaml
from bs4 import BeautifulSoup


STATE_FILE = "state.json"
SOURCES_FILE = "sources.yml"

MAX_ITEMS_PER_SOURCE = 6
MAX_ITEMS_IN_ISSUE = 8
REQUEST_TIMEOUT = 20

MINISTRY_BY_DOMAIN = {
    "abmr.fo": "Almanna- og bústaðamálaráðið",
    "fmr.fo": "Fíggjarmálaráðið",
    "homr.fo": "Heilsu- og orkumálaráðið",
    "lms.fo": "Løgmansskrivstovan",
    "mmr.fo": "Mentamálaráðið",
    "ufmr.fo": "Uttanríkis- og fiskimálaráðið",
    "vmr.fo": "Vinnumálaráðið",
}

ALLOWED_DOMAINS = set(MINISTRY_BY_DOMAIN.keys()) | {
    "www.abmr.fo",
    "www.fmr.fo",
    "www.homr.fo",
    "www.lms.fo",
    "www.mmr.fo",
    "www.ufmr.fo",
    "www.vmr.fo",
    "government.fo",
    "www.government.fo",
    "foroyalandsstyri.fo",
    "www.foroyalandsstyri.fo",
}

HEADERS = {
    "User-Agent": "fo-ministry-watch/1.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

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
    "myndir",
    "fyrispurningar og svar",
    "spurningar og svar",
]


def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_url(url):
    if not url:
        return ""

    url = url.strip()
    parsed = urlparse(url)

    if not parsed.scheme:
        url = "https://" + url
        parsed = urlparse(url)

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]

    return urlunparse((scheme, netloc, path, "", parsed.query, ""))


def domain_without_www(url):
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def ministry_from_url(url, fallback="Føroya landsstýri"):
    host = domain_without_www(url)

    for domain, ministry in MINISTRY_BY_DOMAIN.items():
        if host == domain or host.endswith("." + domain):
            return ministry

    return fallback or "Føroya landsstýri"


def item_id(url, title):
    base_text = normalize_url(url) + "|" + clean_text(title)
    return hashlib.sha256(base_text.encode("utf-8")).hexdigest()


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
    if not os.path.exists(SOURCES_FILE):
        raise FileNotFoundError(f"Fann ikki {SOURCES_FILE}")

    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or []

    if isinstance(data, dict):
        data = data.get("sources", data.get("sites", []))

    sources = []

    for item in data:
        if isinstance(item, str):
            sources.append({
                "name": ministry_from_url(item),
                "url": item,
            })
            continue

        if not isinstance(item, dict):
            continue

        name = item.get("name") or item.get("title") or item.get("source")
        urls = []

        if item.get("url"):
            urls.append(item.get("url"))

        if item.get("feed"):
            urls.append(item.get("feed"))

        if item.get("urls") and isinstance(item.get("urls"), list):
            urls.extend(item.get("urls"))

        if item.get("some") and isinstance(item.get("some"), list):
            urls.extend(item.get("some"))

        for url in urls:
            sources.append({
                "name": name or ministry_from_url(url),
                "url": url,
            })

    return sources


def fetch_html(url):
    response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.text


def is_same_url(a, b):
    return normalize_url(a) == normalize_url(b)


def is_low_value_title(title):
    return clean_text(title).lower() in LOW_VALUE_TITLES


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


def is_allowed_url(url):
    host = urlparse(url).netloc.lower()
    if host in ALLOWED_DOMAINS:
        return True

    host_no_www = host[4:] if host.startswith("www.") else host
    return host_no_www in MINISTRY_BY_DOMAIN


def is_probable_news_url(source_url, href):
    source_lower = source_url.lower()
    href_lower = href.lower()

    if is_same_url(source_url, href):
        return False

    if "hoyringar" in source_lower:
        return "/hoyringar/" in href_lower

    return "/fo/kunning/tidindi/" in href_lower or "/kunning/tidindi/" in href_lower or "/tidindi/" in href_lower


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

    if soup.title:
        title = clean_text(soup.title.get_text(" ", strip=True))
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
                return text[:900]

        og = soup.find("meta", attrs={"property": "og:description"})
        if og and og.get("content"):
            text = clean_text(og.get("content"))
            if len(text) >= 40:
                return text[:900]

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
            return " ".join(paragraphs[:3])[:900]

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

        href = normalize_url(urljoin(base_url, a["href"]))

        if href.startswith("mailto:") or href.startswith("tel:"):
            continue

        if not href.startswith("http"):
            continue

        if not is_allowed_url(href):
            continue

        if not is_probable_news_url(source["url"], href):
            continue

        if is_low_value_title(raw_title):
            continue

        if looks_like_old_archive_item(raw_title, href):
            continue

        correct_source = ministry_from_url(href, source.get("name", "Føroya landsstýri"))

        candidates.append({
            "source": correct_source,
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

        item["source"] = ministry_from_url(item["url"], item.get("source", "Føroya landsstýri"))

        item["summary"] = extract_description_from_page(item["url"])

        if not item["summary"]:
            item["summary"] = item["title"]

        item["id"] = item_id(item["url"], item["title"])

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
        lines.append("**Hví hevur hetta týdning?**")
        lines.append("")
        lines.append("Hetta er nýggj almenn kunning frá einum føroyskum stjórnarráði og kann hava týdning fyri politikk, umsiting, borgarar, skúlar ella stovnar.")
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
            print(f"WARNING: Could not fetch {source.get('name', source.get('url'))}: {e}")
            continue

        for item in items:
            if item["id"] in seen:
                continue

            if is_meaningful(item):
                new_items.append(item)

            seen.add(item["id"])

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
