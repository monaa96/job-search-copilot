"""Company logos, from Google's public favicon service.

The service returns 404 for domains it has no icon for, so each candidate
domain is checked once and the result is stored with the company.
"""

import re
from urllib.parse import urlparse

import requests

LOGO_URL = "https://www.google.com/s2/favicons?domain={domain}&sz=128"
ATS_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com")


def _domain(url_or_domain: str) -> str:
    text = url_or_domain.strip().lower()
    if not text:
        return ""
    host = urlparse(text if "://" in text else f"https://{text}").hostname or ""
    host = host.removeprefix("www.")
    return "" if any(host.endswith(ats) for ats in ATS_HOSTS) else host


def candidate_domains(name: str, website: str = "") -> list[str]:
    """The company's own website first, then guesses from its name."""
    words = re.sub(r"[^a-z0-9 ]", "", name.lower()).split()
    guesses = [f"{''.join(words)}.com", f"{'-'.join(words)}.com"] if words else []
    if len(words) > 1:
        guesses.append(f"{''.join(words)}.ai")
    elif words:
        guesses.append(f"{words[0]}.ai")
    return list(dict.fromkeys(d for d in [_domain(website), *guesses] if d))


def find_logo(name: str, website: str = "") -> tuple[str, str]:
    """(domain, logo URL) for a company, or ("", "") if no logo was found."""
    for domain in candidate_domains(name, website):
        url = LOGO_URL.format(domain=domain)
        try:
            if requests.get(url, timeout=10).status_code == 200:
                return domain, url
        except requests.RequestException:
            continue
    return "", ""
