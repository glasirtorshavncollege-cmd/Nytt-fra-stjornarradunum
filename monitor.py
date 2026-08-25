import os
import re
import json
import smtplib
import hashlib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.parse import urljoin, urlparse, urlunparse

import requests
import yaml
from bs4 import BeautifulSoup


STATE_FILE = "state.json"
SOURCES_FILE = "sources.yml"

REQUEST_TIMEOUT = 20
USER_AGENT = "Glasir ministry monitor/1.0"

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
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


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
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)


def load_sources():
    if not os.path.exists(SOURCES_FILE):
        raise FileNotFoundError(f"Fann ikki {SOURCES_FILE}")

    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    sources = []

    if isinstance(data, list):
        raw_sources = data
    elif isinstance(data, dict):
        raw_sources = data.get("sources", data.get("sites", []))
    else:
        raw_sources = []

    for item in raw_sources:
        if isinstance(item, str):
            sources.append({"name": ministry_from_url(item), "url": item})
            continue

        if not isinstance(item, dict):
            continue

        name = item.get("name") or item.get("title") or item.get("source")
        urls = []

        if item.get("url"):
            urls.append(item.get("url"))

        if item.get("urls") and isinstance(item.get("urls"), list):
            urls.extend(item.get("urls"))

        if item.get("rss"):
            urls.append(item.get("rss"))

        if item.get("some") and isinstance(item.get("some"), list):
            urls.extend(item.get("some"))

        for url in urls:
            sources.append({
                "name": name or ministry_from_url(url),
                "url": url,
            })

    return sources


def fetch_html(url):
    r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.text


def clean_text(text):
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def get_meta_description(soup):
    selectors = [
        ("meta", {"name": "description"}),
        ("meta", {"property": "og:description"}),
        ("meta", {"name": "twitter:description"}),
    ]

    for tag_name, attrs in selectors:
        tag = soup.find(tag_name, attrs=attrs)
        if tag and tag.get("content"):
            return clean_text(tag.get("content"))

    return ""


def get_title(soup):
    h1 = soup.find("h1")
    if h1:
        title = clean_text(h1.get_text(" "))
        if title:
            return title

    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return clean_text(og.get("content"))

    if soup.title:
        return clean_text(soup.title.get_text(" "))

    return "Ókend yvirskrift"


def get_summary(soup):
    desc = get_meta_description(soup)
    if desc:
        return desc[:700]

    paragraphs = []
    for p in soup.find_all("p"):
        t = clean_text(p.get_text(" "))
        if len(t) > 40:
            paragraphs.append(t)

    summary = " ".join(paragraphs[:3])
    if not summary:
        return "Eingin samandráttur funnin."

    return summary[:900]


def looks_like_news_url(url):
    u = url.lower()

    patterns = [
        "/tidindi/",
        "/kunning/tidindi/",
        "/fo/kunning/tidindi/",
        "/news/",
        "/aktuelt/",
    ]

    return any(p in u for p in patterns)


def is_allowed_url(url):
    host = urlparse(url).netloc.lower()
    if host in ALLOWED_DOMAINS:
        return True

    host_no_www = host[4:] if host.startswith("www.") else host
    return host_no_www in MINISTRY_BY_DOMAIN


def discover_article_links(source_url):
    html = fetch_html(source_url)
    soup = BeautifulSoup(html, "html.parser")

    links = []

    for a in soup.find_all("a", href=True):
        href = a.get("href")
        absolute = normalize_url(urljoin(source_url, href))

        if not absolute.startswith("http"):
            continue

        if not is_allowed_url(absolute):
            continue

        if not looks_like_news_url(absolute):
            continue

        text = clean_text(a.get_text(" "))
        links.append({
            "url": absolute,
            "title_hint": text,
        })

    unique = {}
    for link in links:
        unique[link["url"]] = link

    return list(unique.values())


def article_id(url):
    normalized = normalize_url(url)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def read_article(url, fallback_source=None, title_hint=None):
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")

    title = get_title(soup)
    if (not title or title == "Ókend yvirskrift") and title_hint:
        title = title_hint

    source = ministry_from_url(url, fallback_source)

    return {
        "id": article_id(url),
        "title": title,
        "source": source,
        "summary": get_summary(soup),
        "url": normalize_url(url),
    }


def format_briefing(items):
    lines = []
    lines.append("# Nýtt frá føroysku stjórnarráðunum")
    lines.append("")

    for i, item in enumerate(items, 1):
        lines.append(f"### {i}. {item['title']}")
        lines.append("")
        lines.append(f"**Kelda:** {item['source']}")
        lines.append("")
        lines.append("**Samandráttur:**")
        lines.append("")
        lines.append(item["summary"])
        lines.append("")
        lines.append("**Hví hevur hetta týdning?**")
        lines.append("")
        lines.append("Hetta er nýggj almenn kunning frá einum føroyskum stjórnarráði og kann hava týdning fyri politikk, umsiting, borgarar, skúlar ella stovnar.")
        lines.append("")
        lines.append(f"**Les meira:** {item['url']}")
        lines.append("")

    return "\n".join(lines)


def send_email(subject, body):
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    mail_from = os.getenv("MAIL_FROM", smtp_user)
    mail_to = os.getenv("MAIL_TO")

    if not smtp_host or not smtp_user or not smtp_password or not mail_to:
        print(body)
        return

    msg = MIMEMultipart()
    msg["From"] = mail_from
    msg["To"] = mail_to
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(mail_from, [mail_to], msg.as_string())


def main():
    state = load_state()
    seen = set(state.get("seen", []))

    sources = load_sources()

    found_articles = []

    for source in sources:
        source_url = normalize_url(source.get("url", ""))
        fallback_name = source.get("name") or ministry_from_url(source_url)

        if not source_url:
            continue

        try:
            links = discover_article_links(source_url)
        except Exception as e:
            print(f"Feilur við keldu {source_url}: {e}")
            continue

        for link in links:
            url = normalize_url(link["url"])
            aid = article_id(url)

            if aid in seen:
                continue

            try:
                article = read_article(
                    url=url,
                    fallback_source=fallback_name,
                    title_hint=link.get("title_hint"),
                )
                found_articles.append(article)
                seen.add(aid)
            except Exception as e:
                print(f"Feilur við grein {url}: {e}")

    if not found_articles:
        print("No meaningful new updates found.")
        state["seen"] = sorted(seen)
        save_state(state)
        return

    briefing = format_briefing(found_articles)

    send_email(
        subject="Nýtt frá føroysku stjórnarráðunum",
        body=briefing,
    )

    state["seen"] = sorted(seen)
    save_state(state)


if __name__ == "__main__":
    main()
