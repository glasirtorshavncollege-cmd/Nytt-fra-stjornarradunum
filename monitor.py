import hashlib
import json
import os
import re
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Dict, List, Set
from urllib.parse import urljoin

import requests
import yaml
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "state.json"
SOURCES_FILE = BASE_DIR / "sources.yml"

MAIL_TO = os.getenv("MAIL_TO", "samskifti@glasir.fo")
MAIL_FROM = os.getenv("MAIL_FROM")
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")

# Einføld, reglu-baserað meting. Endamálið er at sleppa undan smáum protokoll-fráboðanum.
IMPORTANT_WORDS = [
    "lóg", "lógar", "lógaruppskot", "uppskot", "kunngerð", "hoyring", "hoyringarfreist",
    "játtan", "fíggj", "búskap", "avtala", "samstarvsavtala", "ætlan", "strategi",
    "skipan", "útbúgving", "miðnám", "skúli", "nám", "heils", "sjúkrahús", "psykiatri",
    "bústað", "almanna", "trygd", "verja", "beredskap", "tilbúgving", "fiskivinna",
    "samferðsla", "vinnu", "orka", "umhvørvi", "arbeiðsmarknað", "rættindi", "stjóri",
    "settur", "nevnd", "frágreiðing", "álit", "ráðstevna", "talgild", "vitlíki",
]

LOW_VALUE_WORDS = [
    "vitjan", "móttøka", "heilsan", "myndir", "røða", "setti ráðstevnu", "ynskir tillukku"
]

@dataclass
class Item:
    source: str
    title: str
    url: str
    summary: str
    key: str


def load_sources() -> List[Dict[str, str]]:
    with SOURCES_FILE.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)["sources"]


def load_state() -> Dict[str, List[str]]:
    if not STATE_FILE.exists():
        return {"seen": []}
    with STATE_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state: Dict[str, List[str]]) -> None:
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def make_key(url: str, title: str) -> str:
    raw = f"{url}|{title}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def fetch_html(url: str) -> str:
    headers = {"User-Agent": "Glasir ministry watch/1.0 (+https://glasir.fo)"}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


def extract_items(source_name: str, source_url: str, limit: int = 8) -> List[Item]:
    html = fetch_html(source_url)
    soup = BeautifulSoup(html, "html.parser")

    candidates = []
    for a in soup.find_all("a", href=True):
        title = normalize_space(a.get_text(" "))
        href = a["href"]
        if len(title) < 8:
            continue
        if any(skip in href.lower() for skip in ["mailto:", "tel:", "javascript:"]):
            continue
        full_url = urljoin(source_url, href)
        if not full_url.startswith("http"):
            continue

        # Royn at fáa eitt sindur av tekstinum rundanum leinkið.
        parent_text = normalize_space(a.parent.get_text(" ") if a.parent else title)
        summary = parent_text
        if len(summary) > 350:
            summary = summary[:347].rstrip() + "..."

        # Tíðindasíður hava ofta nógv navigatiónsleinki; hesar reglur taka vanligastu greinar/hoyringar.
        lower_url = full_url.lower()
        looks_like_content = any(part in lower_url for part in ["/tidindi/", "/uppskot", "/kunning/"])
        if not looks_like_content and source_url not in full_url:
            continue

        candidates.append(Item(
            source=source_name,
            title=title,
            url=full_url,
            summary=summary or title,
            key=make_key(full_url, title),
        ))

    # Fjern tvíningar, varðveit raðfylgju.
    seen_urls: Set[str] = set()
    unique: List[Item] = []
    for item in candidates:
        if item.url in seen_urls:
            continue
        seen_urls.add(item.url)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def is_meaningful(item: Item) -> bool:
    text = f"{item.title} {item.summary}".lower()
    important_score = sum(1 for word in IMPORTANT_WORDS if word in text)
    low_value_score = sum(1 for word in LOW_VALUE_WORDS if word in text)

    if important_score >= 2:
        return True
    if important_score == 1 and low_value_score == 0:
        return True
    return False


def make_brief_summary(item: Item) -> str:
    text = item.summary
    if text.lower().startswith(item.title.lower()):
        text = text[len(item.title):].strip(" -–—:.")
    if not text:
        text = item.title
    if len(text) > 260:
        text = text[:257].rstrip() + "..."
    return text


def build_email(items: List[Item]) -> EmailMessage:
    subject = "Nýtt frá stjórnarráðunum"
    lines = ["Nýtt frá stjórnarráðunum", ""]

    for idx, item in enumerate(items, start=1):
        lines.append(f"{idx}. {item.title}")
        lines.append(make_brief_summary(item))
        lines.append(f"Kelda: {item.url}")
        lines.append("")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = MAIL_FROM or SMTP_USER or "ministry-watch@example.com"
    msg["To"] = MAIL_TO
    msg.set_content("\n".join(lines).strip() + "\n")
    return msg


def send_email(msg: EmailMessage) -> None:
    missing = [
        name for name, value in {
            "SMTP_HOST": SMTP_HOST,
            "SMTP_USER": SMTP_USER,
            "SMTP_PASS": SMTP_PASS,
            "MAIL_FROM": MAIL_FROM,
        }.items() if not value
    ]
    if missing:
        raise RuntimeError("Missing mail settings: " + ", ".join(missing))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.starttls()
        smtp.login(SMTP_USER, SMTP_PASS)
        smtp.send_message(msg)


def main() -> None:
    state = load_state()
    seen: Set[str] = set(state.get("seen", []))
    new_meaningful: List[Item] = []
    all_seen_now: Set[str] = set(seen)

    for source in load_sources():
        try:
            items = extract_items(source["name"], source["url"])
        except Exception as exc:
            print(f"WARNING: Could not fetch {source['name']}: {exc}")
            continue

        for item in items:
            all_seen_now.add(item.key)
            if item.key in seen:
                continue
            if is_meaningful(item):
                new_meaningful.append(item)

    if not new_meaningful:
        print("No meaningful new updates. No email sent.")
        state["seen"] = sorted(all_seen_now)
        save_state(state)
        return

    msg = build_email(new_meaningful)
    send_email(msg)
    print(f"Sent email with {len(new_meaningful)} update(s) to {MAIL_TO}.")

    state["seen"] = sorted(all_seen_now)
    save_state(state)


if __name__ == "__main__":
    main()
