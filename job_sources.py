"""Public job feeds from the hiring systems most tech companies use.

Greenhouse, Lever and Ashby each publish an official, unauthenticated JSON
feed of a company's open jobs, keyed by a short company "slug"
(e.g. boards-api.greenhouse.io/v1/boards/<slug>/jobs). This module finds a
company's slug and turns each feed into the same simple job shape.
"""

import html
import re
from datetime import datetime, timezone

import requests

TIMEOUT = 20
HEADERS = {"User-Agent": "job-search-copilot (personal job search tool)"}

FEED_URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}

# Links that reveal which system a careers page uses, and the company's slug on it.
BOARD_LINK_PATTERNS = [
    ("greenhouse", r"greenhouse\.io/embed/job_board(?:/js)?\?for=([\w-]+)"),
    ("greenhouse", r"boards-api\.greenhouse\.io/v1/boards/([\w-]+)"),
    ("greenhouse", r"(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io/(?!embed\b)([\w-]+)"),
    ("lever", r"jobs\.lever\.co/([\w-]+)"),
    ("lever", r"api\.lever\.co/v0/postings/([\w-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([\w.%-]+)"),
    ("ashby", r"api\.ashbyhq\.com/posting-api/job-board/([\w.%-]+)"),
]


def _strip_html(text: str) -> str:
    text = re.sub(r"<(br|/p|/li|/h\d)\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(text)).strip()


def _get_feed(ats: str, slug: str):
    r = requests.get(FEED_URLS[ats].format(slug=slug), headers=HEADERS, timeout=TIMEOUT)
    if r.status_code != 200:
        return None
    data = r.json()
    if isinstance(data, dict) and data.get("ok") is False:
        return None
    return data


def board_exists(ats: str, slug: str) -> bool:
    try:
        return _get_feed(ats, slug) is not None
    except (requests.RequestException, ValueError):
        return False


def _slug_candidates(name: str) -> list[str]:
    words = re.sub(r"[^a-z0-9 ]", "", name.lower()).split()
    if not words:
        return []
    candidates = ["".join(words), "-".join(words)]
    if len(words) > 1:
        candidates.append(words[0])
    return list(dict.fromkeys(candidates))


def find_board(name: str, careers_url: str = "") -> tuple[str, str] | None:
    """Find (ats, slug) for a company, or None if it has no public feed we support.

    Tries, in order: the careers URL itself, links on the careers page, then
    slugs guessed from the company name.
    """
    candidates: list[tuple[str, str]] = []

    def collect(text: str) -> None:
        for ats, pattern in BOARD_LINK_PATTERNS:
            for slug in re.findall(pattern, text, flags=re.I):
                candidates.append((ats, slug.lower()))

    if careers_url:
        collect(careers_url)
        if not candidates:
            try:
                page = requests.get(careers_url, headers=HEADERS, timeout=TIMEOUT)
                collect(page.text)
            except requests.RequestException:
                pass

    for slug in _slug_candidates(name):
        for ats in FEED_URLS:
            candidates.append((ats, slug))

    for ats, slug in dict.fromkeys(candidates):
        if board_exists(ats, slug):
            return ats, slug
    return None


def _iso_from_ms(ms) -> str | None:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat() if ms else None


def fetch_jobs(ats: str, slug: str) -> list[dict]:
    """All open jobs on a board, as dicts with: external_id, title, location, url, description, posted_at."""
    data = _get_feed(ats, slug)
    if data is None:
        raise RuntimeError(f"No {ats} job board found for '{slug}'")

    jobs = []
    if ats == "greenhouse":
        for j in data.get("jobs", []):
            jobs.append({
                "external_id": str(j["id"]),
                "title": j.get("title", ""),
                "location": (j.get("location") or {}).get("name", ""),
                "url": j.get("absolute_url", ""),
                "description": _strip_html(html.unescape(j.get("content") or "")),
                "posted_at": j.get("first_published") or j.get("updated_at"),
            })
    elif ats == "lever":
        for j in data:
            cats = j.get("categories") or {}
            locations = [cats.get("location") or ""] + (cats.get("allLocations") or [])
            sections = [j.get("descriptionPlain") or ""]
            for lst in j.get("lists") or []:
                sections.append(f"{lst.get('text', '')}\n{_strip_html(lst.get('content', ''))}")
            sections.append(j.get("additionalPlain") or "")
            jobs.append({
                "external_id": j["id"],
                "title": j.get("text", ""),
                "location": " | ".join(dict.fromkeys(l for l in locations if l)),
                "url": j.get("hostedUrl", ""),
                "description": "\n\n".join(s for s in sections if s.strip()),
                "posted_at": _iso_from_ms(j.get("createdAt")),
            })
    elif ats == "ashby":
        for j in data.get("jobs", []):
            if j.get("isListed") is False:
                continue
            locations = [j.get("location") or ""]
            locations += [s.get("location", "") for s in j.get("secondaryLocations") or []]
            if j.get("isRemote"):
                locations.append("Remote")
            jobs.append({
                "external_id": j["id"],
                "title": j.get("title", ""),
                "location": " | ".join(dict.fromkeys(l for l in locations if l)),
                "url": j.get("jobUrl", ""),
                "description": j.get("descriptionPlain") or _strip_html(j.get("descriptionHtml") or ""),
                "posted_at": j.get("publishedAt"),
            })
    return jobs


BOARD_PAGE_URLS = {
    "greenhouse": "https://job-boards.greenhouse.io/{slug}",
    "lever": "https://jobs.lever.co/{slug}",
    "ashby": "https://jobs.ashbyhq.com/{slug}",
}


def board_page_url(ats: str, slug: str) -> str:
    return BOARD_PAGE_URLS[ats].format(slug=slug)
