"""Referrals: matching a user's LinkedIn connections to companies, and drafting the ask.

Connections come from LinkedIn's official data export (Connections.csv). The
app stores names, companies, titles and profile links only, never emails, and
never contacts anyone: it drafts messages for the user to send themselves.
"""

import csv
import io
import re
from dataclasses import dataclass

import anthropic

from analyzer import MODEL, JobFitAnalysis, resume_block

COMPANY_SUFFIXES = {"inc", "llc", "ltd", "limited", "corp", "corporation", "co", "company", "plc", "gmbh",
                    "technologies", "technology", "labs", "hq", "group", "holdings", "the"}


def company_key(name: str) -> str:
    """Normalize a company name for matching: 'Ramp Business Corp.' → 'ramp business'."""
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    return " ".join(w for w in words if w not in COMPANY_SUFFIXES)


def same_company(connection_company: str, target: str) -> bool:
    a, b = company_key(connection_company), company_key(target)
    if not a or not b:
        return False
    if a == b:
        return True
    # "ramp" matches "ramp financial", but short names must match exactly to avoid false hits.
    shorter, longer = sorted((a, b), key=len)
    return len(shorter) >= 4 and longer.startswith(shorter + " ")


def parse_linkedin_csv(data: bytes) -> list[dict]:
    """Parse LinkedIn's Connections.csv, which starts with a few lines of notes before the header."""
    text = data.decode("utf-8-sig", errors="ignore")
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("First Name")), None)
    if start is None:
        raise ValueError("This doesn't look like LinkedIn's Connections.csv (no 'First Name' header found).")
    people = []
    for row in csv.DictReader(io.StringIO("\n".join(lines[start:]))):
        name = f"{row.get('First Name', '').strip()} {row.get('Last Name', '').strip()}".strip()
        company = (row.get("Company") or "").strip()
        if name and company:
            people.append({"name": name, "company": company, "position": (row.get("Position") or "").strip(),
                           "url": (row.get("URL") or "").strip(), "connected_on": (row.get("Connected On") or "").strip()})
    return people


# --- Who to ask ------------------------------------------------------------------------

@dataclass
class Contact:
    name: str
    position: str
    url: str
    why: str
    rank: int


RECRUITING = ("recruit", "talent", "people partner", "sourcer", "hiring")
SENIOR = ("head", "director", "vp", "vice president", "chief", "manager", "lead", "principal")
FUNCTIONS = {"product": ("product",), "engineering": ("engineer", "developer", "software"),
             "design": ("design", "ux", "ui"), "data": ("data", "analytics", "scientist"),
             "marketing": ("marketing", "growth"), "sales": ("sales", "account executive", "partnerships")}


def _function(title: str) -> str | None:
    title = title.lower()
    return next((f for f, words in FUNCTIONS.items() if any(w in title for w in words)), None)


def rank_contacts(connections: list[dict], role_title: str, limit: int = 5) -> list[Contact]:
    """Order connections at a company by how useful they are for this role."""
    role_function = _function(role_title)
    contacts = []
    for c in connections:
        position = c["position"].lower()
        if any(w in position for w in RECRUITING):
            why, rank = "Works in recruiting, so can refer you or route your application directly", 0
        elif role_function and _function(position) == role_function:
            why, rank = "Works in the same function, so knows the team and can speak to the role", 1
        elif any(w in position for w in SENIOR):
            why, rank = "Senior enough to introduce you to the hiring manager", 2
        else:
            why, rank = "Can share what it's like inside and submit a referral", 3
        contacts.append(Contact(c["name"], c["position"], c["url"], why, rank))
    return sorted(contacts, key=lambda c: c.rank)[:limit]


# --- Drafting the ask ------------------------------------------------------------------

DRAFT_SYSTEM = """You write short, warm, specific LinkedIn messages asking a connection for a referral \
or a quick chat about a role. Rules:
- Under 110 words. No subject line. Plain text, no placeholders like [Name] except the connection's first name.
- Open with a genuine, specific line (not "I hope this finds you well").
- Say which role, and in one sentence why the sender is a strong fit, using real evidence from their resume.
- Make one clear, easy ask: a referral, or 15 minutes to learn about the team. Offer to send a resume.
- Never invent shared history, mutual friends, or experience the resume doesn't show."""


def draft_message(contact: Contact, role_title: str, company: str, analysis: JobFitAnalysis | None,
                  resume_text: str | None, resume_pdf: bytes | None,
                  client: anthropic.Anthropic | None = None) -> str:
    client = client or anthropic.Anthropic()
    angle = analysis.what_to_emphasize[0] if analysis and analysis.what_to_emphasize else ""
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=DRAFT_SYSTEM,
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": [
            resume_block(resume_text, resume_pdf),
            {"type": "text", "text": (
                f"Write a message to {contact.name} ({contact.position} at {company}), a LinkedIn connection, "
                f"about the {role_title} role at {company}."
                + (f"\nThe strongest angle for this candidate: {angle}" if angle else "")
            )},
        ]}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Couldn't draft a message for this contact.")
    return "\n".join(b.text for b in response.content if b.type == "text").strip()
