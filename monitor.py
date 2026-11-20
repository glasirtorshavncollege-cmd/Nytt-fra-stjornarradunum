
import argparse
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

MAX_ITEMS_PER_SOURCE = 8
MAX_ITEMS_IN_ISSUE = 12
REQUEST_TIMEOUT = 20

MINISTRY_BY_DOMAIN = {
    "abmr.fo": "Almanna- og bústaðamálaráðið",
    "fmr.fo": "Fíggjarmálaráðið",
    "homr.fo": "Heilsu- og orkumálaráðið",
    "lms.fo": "Løgmansskrivstovan",
    "mmr.fo": "Mentamálaráðið",
    "ufmr.fo": "Uttanríkis- og fiskimálaráðið",
    "vmr.fo": "Vinnumálaráðið",
    "lum.fo": "Løgtingsins umboðsmaður",
    "logting.fo": "Løgtingið",
}

ALLOWED_DOMAINS = set(MINISTRY_BY_DOMAIN.keys()) | {
    "www.abmr.fo",
    "www.fmr.fo",
    "www.homr.fo",
    "www.lms.fo",
    "www.mmr.fo",
    "www.ufmr.fo",
    "www.vmr.fo",
    "www.lum.fo",
    "www.logting.fo",
    "government.fo",
    "www.government.fo",
    "foroyalandsstyri.fo",
    "www.foroyalandsstyri.fo",
}

HEADERS = {
    "User-Agent": "fo-ministry-watch/1.0",
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
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


def log(message):
    print(message, flush=True)


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

    return urlunparse(
        (scheme, netloc, path, "", parsed.query, "")
    )


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
    base_text = (
        normalize_url(url) + "|" + clean_text(title)
    )
    return hashlib.sha256(
        base_text.encode("utf-8")
    ).hexdigest()


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"seen": []}

    try:
        with open(
            STATE_FILE, "r", encoding="utf-8"
        ) as f:
            data = json.load(f)

        if "seen" not in data:
            data["seen"] = []

        return data
    except Exception:
        return {"seen": []}


def save_state(state):
    state["updated_at"] = datetime.now(
        timezone.utc
    ).isoformat()

    state["seen"] = list(
        dict.fromkeys(state.get("seen", []))
    )[-2000:]

    with open(
        STATE_FILE, "w", encoding="utf-8"
    ) as f:
        json.dump(
            state, f, ensure_ascii=False, indent=2
        )


def load_sources():
    if not os.path.exists(SOURCES_FILE):
        raise FileNotFoundError(
            f"Fann ikki {SOURCES_FILE}"
        )

    with open(
        SOURCES_FILE, "r", encoding="utf-8"
    ) as f:
        data = yaml.safe_load(f) or []

    if isinstance(data, dict):
        data = data.get(
            "sources", data.get("sites", [])
        )

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

        name = (
            item.get("name")
            or item.get("title")
            or item.get("source")
        )

        urls = []

        if item.get("url"):
            urls.append(item.get("url"))

        if item.get("feed"):
            urls.append(item.get("feed"))

        if (
            item.get("urls")
            and isinstance(item.get("urls"), list)
        ):
            urls.extend(item.get("urls"))

        if (
            item.get("some")
            and isinstance(item.get("some"), list)
        ):
            urls.extend(item.get("some"))

        for url in urls:
            sources.append({
                "name": name or ministry_from_url(url),
                "url": url,
            })

    return sources


def fetch_html(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.text


def is_same_url(a, b):
    return normalize_url(a) == normalize_url(b)


def is_low_value_title(title):
    return (
        clean_text(title).lower()
        in LOW_VALUE_TITLES
    )


def is_placeholder_title(title):
    return (
        clean_text(title)
        .lower()
        .rstrip(" .…")
        in {
            "les meira",
            "les meir",
            "read more",
            "more",
            "víðari",
        }
    )


def looks_like_old_archive_item(title, url):
    text = f"{title} {url}".lower()

    patterns = [
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

    return any(
        pattern in text for pattern in patterns
    )


def is_allowed_url(url):
    host = urlparse(url).netloc.lower()

    if host in ALLOWED_DOMAINS:
        return True

    host_no_www = (
        host[4:]
        if host.startswith("www.")
        else host
    )

    return host_no_www in MINISTRY_BY_DOMAIN


def is_lum_url(url):
    return (
        "lum.fo"
        in urlparse(url).netloc.lower()
    )


def is_logting_url(url):
    return (
        "logting.fo"
        in urlparse(url).netloc.lower()
    )


def is_probable_news_url(source_url, href):
    href_lower = href.lower()
    source_lower = source_url.lower()

    if is_same_url(source_url, href):
        return False

    if is_lum_url(href):
        blocked = [
            "/um-embaeti",
            "/loggava",
            "/english",
            "/samband",
            "/files/",
            "/ajaxfilter",
            "?id=",
        ]

        if any(
            part in href_lower for part in blocked
        ):
            return False

        return True

    if is_logting_url(href):
        return (
            "/hvat-hendir-i-logtinginum/"
            "tidindi/tidindasavn/"
            in href_lower
        )

    if "hoyringar" in source_lower:
        return "/hoyringar/" in href_lower

    return (
        "/fo/kunning/tidindi/" in href_lower
        or "/kunning/tidindi/" in href_lower
        or "/tidindi/" in href_lower
    )


def find_nearby_title(a_tag):
    parent = a_tag.find_parent()

    if not parent:
        return ""

    for tag in parent.find_all(
        ["h1", "h2", "h3", "h4", "strong"]
    ):
        text = clean_text(tag.get_text(" "))

        if (
            len(text) >= 8
            and text.lower() != "nýggjasta"
            and not is_placeholder_title(text)
        ):
            return text

    previous = parent.find_previous(
        ["h1", "h2", "h3", "h4"]
    )

    if previous:
        text = clean_text(
            previous.get_text(" ")
        )

        if (
            len(text) >= 8
            and not is_placeholder_title(text)
        ):
            return text

    return ""


def extract_lum_latest_links(source_url, soup):
    headings = soup.find_all(
        ["h1", "h2", "h3"]
    )

    latest_heading = None

    for h in headings:
        if (
            clean_text(h.get_text(" ")).lower()
            == "nýggjasta"
        ):
            latest_heading = h
            break

    if not latest_heading:
        return []

    container = latest_heading.find_parent()

    if not container:
        return []

    for _ in range(4):
        parent = container.find_parent()
        if parent:
            container = parent

    links = []

    for a in container.find_all(
        "a", href=True
    ):
        text = clean_text(a.get_text(" "))
        href = normalize_url(
            urljoin(
                source_url,
                a.get("href"),
            )
        )

        if not href.startswith("http"):
            continue

        if not is_allowed_url(href):
            continue

        if not is_lum_url(href):
            continue

        if is_same_url(source_url, href):
            continue

        if text.lower() in [
            "les meira", "les meir"
        ]:
            title = find_nearby_title(a)
        else:
            title = text

        if not title or len(title) < 8:
            title = (
                href.rstrip("/")
                .split("/")[-1]
                .replace("-", " ")
            )

        links.append({
            "url": href,
            "title_hint": title[:180],
        })

    unique = {}

    for link in links:
        unique[link["url"]] = link

    return list(unique.values())[
        :MAX_ITEMS_PER_SOURCE
    ]


def extract_items(source):
    html = fetch_html(source["url"])
    soup = BeautifulSoup(
        html, "html.parser"
    )
    base_url = source["url"]

    if "lum.fo" in base_url.lower():
        raw_links = extract_lum_latest_links(
            base_url, soup
        )
    else:
        raw_links = []

        for a in soup.find_all(
            "a", href=True
        ):
            raw_title = clean_text(
                a.get_text(" ", strip=True)
            )

            href = normalize_url(
                urljoin(
                    base_url, a["href"]
                )
            )

            if href.startswith(
                ("mailto:", "tel:")
            ):
                continue

            if not href.startswith("http"):
                continue

            if not is_allowed_url(href):
                continue

            if not is_probable_news_url(
                source["url"], href
            ):
                continue

            if is_placeholder_title(
                raw_title
            ):
                raw_title = (
                    find_nearby_title(a)
                    or raw_title
                )

            if is_low_value_title(
                raw_title
            ):
                continue

            if looks_like_old_archive_item(
                raw_title, href
            ):
                continue

            if (
                not raw_title
                or len(raw_title) < 8
            ):
                raw_title = (
                    href.rstrip("/")
                    .split("/")[-1]
                    .replace("-", " ")
                )

            raw_links.append({
                "url": href,
                "title_hint": raw_title[:180],
            })

    candidates = []

    for link in raw_links:
        href = normalize_url(
            link["url"]
        )

        raw_title = clean_text(
            link.get("title_hint", "")
        )

        if is_low_value_title(
            raw_title
        ):
            continue

        if looks_like_old_archive_item(
            raw_title, href
        ):
            continue

        correct_source = ministry_from_url(
            href,
            source.get(
                "name",
                "Føroya landsstýri",
            ),
        )

        candidates.append({
            "source": correct_source,
            "title": raw_title[:180],
            "url": href,
            "summary": "",
            "id": item_id(
                href, raw_title
            ),
        })

    seen_urls = set()
    unique = []

    for item in candidates:
        key = normalize_url(
            item["url"]
        )

        if key in seen_urls:
            continue

        seen_urls.add(key)
        unique.append(item)

    return unique[:MAX_ITEMS_PER_SOURCE]


def is_meaningful(item):
    text = (
        f"{item.get('source', '')} "
        f"{item.get('title', '')} "
        f"{item.get('summary', '')} "
        f"{item.get('url', '')}"
    ).lower()

    if is_low_value_title(
        item.get("title", "")
    ):
        return False

    if looks_like_old_archive_item(
        item.get("title", ""),
        item.get("url", ""),
    ):
        return False

    if any(
        keyword in text
        for keyword in LOW_VALUE_KEYWORDS
    ):
        return False

    return True


def extract_page_title(soup, fallback):
    for attr, name in [
        ("property", "og:title"),
        ("name", "twitter:title"),
    ]:
        tag = soup.find(
            "meta",
            attrs={attr: name},
        )

        if tag and tag.get("content"):
            title = clean_text(
                tag["content"]
            )

            if (
                len(title) >= 8
                and not is_placeholder_title(title)
            ):
                return title

    for tag in soup.find_all(
        ["h1", "h2"], limit=20
    ):
        title = clean_text(
            tag.get_text(" ", strip=True)
        )

        if (
            len(title) >= 8
            and not is_placeholder_title(title)
        ):
            return title

    if soup.title:
        title = clean_text(
            soup.title.get_text(
                " ", strip=True
            )
        )

        if (
            len(title) >= 8
            and not is_placeholder_title(title)
        ):
            return title

    if not is_placeholder_title(
        fallback
    ):
        return fallback

    return ""


def parse_publication_date(value):
    if not isinstance(value, str):
        return None

    match = re.match(
        r"^\s*(\d{4}-\d{2}-\d{2})(?:[Tt ]|$)",
        value,
    )

    if not match:
        return None

    try:
        date = datetime.strptime(
            match.group(1),
            "%Y-%m-%d",
        ).date()

        if (
            date
            > datetime.now(timezone.utc).date()
        ):
            return None

        return date.isoformat()

    except ValueError:
        return None


def extract_published_at(soup):
    keys = [
        ("property", "article:published_time"),
        ("name", "article:published_time"),
        ("name", "datePublished"),
        ("itemprop", "datePublished"),
        ("name", "publish-date"),
        ("name", "pubdate"),
        ("name", "DC.date.issued"),
    ]

    for key, value in keys:
        tag = soup.find(
            ["meta", "time"],
            attrs={key: value},
        )

        if tag:
            day = parse_publication_date(
                tag.get("content")
                or tag.get("datetime")
            )

            if day:
                return day

    scripts = soup.find_all(
        "script",
        attrs={
            "type": "application/ld+json"
        },
    )

    def walk(node):
        if isinstance(node, dict):
            kinds = node.get(
                "@type", []
            )

            if isinstance(kinds, str):
                kinds = [kinds]

            accepted = {
                "newsarticle",
                "article",
                "blogposting",
                "reportage",
            }

            if any(
                str(kind).lower()
                in accepted
                for kind in kinds
            ):
                day = parse_publication_date(
                    node.get("datePublished")
                )

                if day:
                    return day

            for child in node.values():
                day = walk(child)
                if day:
                    return day

        elif isinstance(node, list):
            for child in node:
                day = walk(child)
                if day:
                    return day

        return None

    for script in scripts:
        try:
            obj = json.loads(
                script.string
                or script.get_text()
            )
        except (
            ValueError,
            TypeError,
        ):
            continue

        day = walk(obj)

        if day:
            return day

    for tag in soup.find_all(
        "time",
        attrs={"datetime": True},
        limit=15,
    ):
        day = parse_publication_date(
            tag.get("datetime")
        )

        if day:
            return day

    return None


def extract_description_from_soup(soup):
    for attrs in [
        {"name": "description"},
        {"property": "og:description"},
    ]:
        tag = soup.find(
            "meta", attrs=attrs
        )

        if tag and tag.get("content"):
            text = clean_text(
                tag["content"]
            )

            if len(text) >= 40:
                return text[:900]

    paragraphs = []

    for p in soup.find_all("p"):
        text = clean_text(
            p.get_text(" ", strip=True)
        )

        if len(text) < 60:
            continue

        lower = text.lower()

        skip_phrases = [
            "cookies",
            "far til innihald",
            "les meira",
            "les meir",
            "deil",
            "facebook",
            "linkedin",
            "twitter",
            "teldupost",
            "©",
        ]

        if any(
            skip in lower
            for skip in skip_phrases
        ):
            continue

        paragraphs.append(text)

    if paragraphs:
        return " ".join(
            paragraphs[:3]
        )[:900]

    return ""


def enrich_items(items):
    enriched = []

    for original in items:
        item = dict(original)

        try:
            soup = BeautifulSoup(
                fetch_html(item["url"]),
                "html.parser",
            )

            title = extract_page_title(
                soup,
                item.get("title", ""),
            )

            if title:
                item["title"] = title

            summary = (
                extract_description_from_soup(
                    soup
                )
            )

            if summary:
                item["summary"] = summary

            day = extract_published_at(
                soup
            )

            if day:
                item["published_at"] = day

        except Exception as error:
            log(
                "WARNING: Could not enrich "
                f"{item['url']}: {error}"
            )

        item["source"] = ministry_from_url(
            item["url"],
            item.get(
                "source",
                "Føroya landsstýri",
            ),
        )

        item["summary"] = (
            item.get("summary")
            or item.get("title", "")
        )

        enriched.append(item)

    return enriched


def make_summary(item):
    summary = clean_text(
        item.get("summary", "")
    )

    if not summary:
        return item["title"]

    return summary


def build_issue_body(items):
    lines = [
        "## Nýtt frá stjórnarráðunum",
        "",
        (
            "Her er stuttur samandráttur "
            "av nýggjum almennum dagføringum "
            "frá stjórnarráðunum, LUM og "
            "Løgtinginum."
        ),
        "",
    ]

    for i, item in enumerate(
        items, 1
    ):
        lines.extend([
            f"### {i}. {item['title']}",
            "",
            f"**Kelda:** {item['source']}",
            "",
            "**Samandráttur:**",
            "",
            make_summary(item),
            "",
            "**Hví hevur hetta týdning?**",
            "",
            (
                "Hetta er nýggj almenn kunning, "
                "sum kann hava týdning fyri "
                "politikk, umsiting, borgarar, "
                "skúlar ella stovnar."
            ),
            "",
            f"**Les meira:** {item['url']}",
            "",
        ])

    lines.append("---")
    lines.append(
        "Automatiskt stovnað: "
        + datetime.now(
            timezone.utc
        ).strftime("%Y-%m-%d %H:%M UTC")
    )

    return "\n".join(lines)


def create_github_issue(title, body):
    repo = os.environ.get(
        "GITHUB_REPOSITORY"
    )
    token = os.environ.get(
        "GITHUB_TOKEN"
    )

    if not repo:
        raise RuntimeError(
            "Missing GITHUB_REPOSITORY"
        )

    if not token:
        raise RuntimeError(
            "Missing GITHUB_TOKEN"
        )

    url = (
        f"https://api.github.com/"
        f"repos/{repo}/issues"
    )

    payload = {
        "title": title,
        "body": body,
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "fo-ministry-watch/1.0",
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=20,
    )
    response.raise_for_status()

    return response.json().get(
        "html_url"
    )


def update_public_feed(items):
    feed_path = os.path.join(
        "docs", "feed.json"
    )
    os.makedirs(
        "docs", exist_ok=True
    )

    try:
        with open(
            feed_path,
            "r",
            encoding="utf-8",
        ) as file:
            feed = json.load(file)

        if not isinstance(feed, list):
            raise ValueError(
                "docs/feed.json must contain a list"
            )

    except FileNotFoundError:
        feed = []

    existing_urls = {
        normalize_url(
            article.get("url", "")
        )
        for article in feed
        if isinstance(article, dict)
    }

    found_at = datetime.now(
        timezone.utc
    ).isoformat()

    added = 0

    for item in items:
        url = normalize_url(
            item["url"]
        )

        if url in existing_urls:
            continue

        if is_placeholder_title(
            item.get("title", "")
        ):
            log(
                "WARNING: Skipping article "
                f"without reliable title: {url}"
            )
            continue

        entry = {
            "id": item["id"],
            "title": clean_text(
                item["title"]
            ),
            "source": clean_text(
                item["source"]
            ),
            "summary": make_summary(item),
            "url": item["url"],
            "found_at": found_at,
        }

        if item.get("published_at"):
            entry["published_at"] = (
                item["published_at"]
            )

        feed.insert(0, entry)
        existing_urls.add(url)
        added += 1

    temporary = feed_path + ".tmp"

    with open(
        temporary,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            feed[:500],
            file,
            ensure_ascii=False,
            indent=2,
        )

    os.replace(
        temporary, feed_path
    )

    return added


def repair_public_feed():
    feed_path = os.path.join(
        "docs", "feed.json"
    )

    if not os.path.isfile(
        feed_path
    ):
        return 0

    with open(
        feed_path,
        encoding="utf-8",
    ) as file:
        feed = json.load(file)

    if not isinstance(feed, list):
        raise ValueError(
            "docs/feed.json must be an array"
        )

    changed = 0

    for entry in feed:
        if not isinstance(
            entry, dict
        ):
            continue

        if not is_allowed_url(
            entry.get("url", "")
        ):
            continue

        try:
            soup = BeautifulSoup(
                fetch_html(entry["url"]),
                "html.parser",
            )

            title = extract_page_title(
                soup,
                entry.get("title", ""),
            )

            if (
                title
                and not is_placeholder_title(title)
                and title != entry.get("title")
            ):
                entry["title"] = title
                changed += 1

            day = extract_published_at(
                soup
            )

            if (
                day
                and day != entry.get("published_at")
            ):
                entry["published_at"] = day
                changed += 1

            if (
                not entry.get("summary")
                or is_placeholder_title(
                    entry.get("summary", "")
                )
            ):
                summary = (
                    extract_description_from_soup(
                        soup
                    )
                )

                if summary:
                    entry["summary"] = summary
                    changed += 1

        except Exception as error:
            log(
                "WARNING: Could not repair "
                f"{entry['url']}: {error}"
            )

    temporary = feed_path + ".tmp"

    with open(
        temporary,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            feed,
            file,
            ensure_ascii=False,
            indent=2,
        )

    os.replace(
        temporary, feed_path
    )

    return changed


def load_public_feed_urls():
    path = os.path.join(
        "docs", "feed.json"
    )

    if not os.path.isfile(path):
        return set()

    with open(
        path,
        encoding="utf-8",
    ) as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError(
            "docs/feed.json must contain a list"
        )

    return {
        normalize_url(
            article.get("url", "")
        )
        for article in data
        if (
            isinstance(article, dict)
            and article.get("url")
        )
    }


def was_already_seen(item, seen, feed_urls):
    url = normalize_url(
        item["url"]
    )

    if (
        url in feed_urls
        or item["id"] in seen
    ):
        return True

    legacy_titles = (
        "Les meira...",
        "Les meira",
        "Les meir",
        "Les meir...",
    )

    return any(
        item_id(url, title) in seen
        for title in legacy_titles
    )


def collect_candidates(sources):
    candidates = []
    urls = set()
    checked_sources = 0

    for source in sources:
        source_name = source.get(
            "name",
            source.get(
                "url", "Ókend kelda"
            ),
        )

        try:
            items = extract_items(
                source
            )
            checked_sources += 1

        except Exception as error:
            log(
                "WARNING: Could not fetch "
                f"{source_name}: {error}"
            )
            continue

        for item in items:
            url = normalize_url(
                item["url"]
            )

            if url not in urls:
                candidates.append(item)
                urls.add(url)

        log(
            f"Checked source: {source_name} | "
            f"links found: {len(items)}"
        )

    return candidates, checked_sources


def main():
    parser = argparse.ArgumentParser(
        description="Ministry news monitor"
    )

    mode = (
        parser.add_mutually_exclusive_group()
    )

    mode.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Find potential updates but "
            "do not save files or send issues"
        ),
    )

    mode.add_argument(
        "--backfill-feed",
        action="store_true",
        help=(
            "Populate docs/feed.json from "
            "visible articles without "
            "issues or state changes"
        ),
    )

    args = parser.parse_args()

    state = load_state()
    seen = set(
        state.get("seen", [])
    )

    feed_urls = (
        load_public_feed_urls()
    )

    sources = load_sources()

    log(
        f"Configured sources: {len(sources)}"
    )

    candidates, checked = (
        collect_candidates(sources)
    )

    log(
        f"Checked sources: {checked}"
    )

    log(
        f"Candidate links: {len(candidates)}"
    )

    if args.backfill_feed:
        selected = [
            item
            for item in candidates
            if is_meaningful(item)
        ]

        enriched = enrich_items(
            selected
        )

        added = update_public_feed(
            enriched
        )

        repaired = repair_public_feed()

        log(
            "Existing feed fields repaired: "
            f"{repaired}"
        )

        log(
            f"Backfill complete: {added} "
            "articles added to docs/feed.json"
        )

        log(
            "No GitHub Issue created; "
            "state.json unchanged"
        )
        return

    new_items = []
    rejected_ids = set()
    recognized_ids = set()

    for item in candidates:
        if was_already_seen(
            item, seen, feed_urls
        ):
            recognized_ids.add(
                item["id"]
            )
            continue

        if not is_meaningful(item):
            rejected_ids.add(
                item["id"]
            )
        else:
            new_items.append(item)

    log(
        "Already known (state or PWA feed): "
        f"{len(recognized_ids)}"
    )

    log(
        "New meaningful updates: "
        f"{len(new_items)}"
    )

    selected = new_items[
        :MAX_ITEMS_IN_ISSUE
    ]

    if (
        len(new_items)
        > len(selected)
    ):
        log(
            "Deferred to future runs: "
            f"{len(new_items) - len(selected)}"
        )

    if args.dry_run:
        for item in selected:
            log(
                f"PREVIEW: {item['source']} | "
                f"{item['title']} | "
                f"{item['url']}"
            )

        log(
            "Dry run: state/feed unchanged; "
            "no GitHub Issue"
        )
        return

    if not selected:
        if (
            rejected_ids
            or recognized_ids
        ):
            state["seen"] = list(
                seen
                | rejected_ids
                | recognized_ids
            )

            save_state(state)

        log(
            "No meaningful new updates "
            "found; no GitHub Issue"
        )
        return

    enriched = enrich_items(
        selected
    )

    today = datetime.now(
        timezone.utc
    ).strftime("%d.%m.%Y")

    issue_title = (
        "Nýtt frá stjórnarráðunum - "
        f"{today}"
    )

    issue_body = build_issue_body(
        enriched
    )

    issue_url = create_github_issue(
        issue_title, issue_body
    )

    log(
        f"Created issue: {issue_url}"
    )

    added = update_public_feed(
        enriched
    )

    log(
        "Public feed articles added: "
        f"{added}"
    )

    state["seen"] = list(
        seen
        | rejected_ids
        | recognized_ids
        | {
            item["id"]
            for item in selected
        }
    )

    save_state(state)

    log("State updated")


if __name__ == "__main__":
    main()
