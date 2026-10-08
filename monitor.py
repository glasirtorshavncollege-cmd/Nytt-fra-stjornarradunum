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
    "løgtingsins umboðsmaður",
    "løgtingið",
]

LOW_VALUE_KEYWORDS = [
    "myndir",
    "fyrispurningar og svar",
    "spurningar og svar",
]

LUM_BLOCKED_URL_PARTS = [
    "/um-embaeti",
    "/loggava",
    "/english",
    "/samband",
    "/files/",
    "/ajaxfilter",
    "?id=",
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
