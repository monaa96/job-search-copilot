"""Turns a fit analysis into a plan to land the role.

The plan is assembled from the analysis with plain rules rather than another
AI call, so it's free, instant and predictable. Adjacent role *types* come
from the analysis (AI judgment); matching them to real openings is done here
(software), so every suggestion points to a job that actually exists.
"""

import re
from dataclasses import dataclass

from analyzer import JobFitAnalysis


@dataclass
class Recommendation:
    headline: str
    detail: str
    color: str  # badge color: green | blue | orange | gray


@dataclass
class PlanStep:
    key: str  # stable id, used to remember which steps are done
    kind: str  # resume | skill | referral | story | adjacent | apply
    title: str
    detail: str


def fit_label(score: int) -> tuple[str, str]:
    """(label, color) for a fit score, matching the scoring rubric."""
    if score >= 85:
        return "Strong fit", "green"
    if score >= 70:
        return "Good fit", "blue"
    if score >= 50:
        return "Stretch", "orange"
    return "Long shot", "gray"


def recommendation(score: int, company: str) -> Recommendation:
    if score >= 85:
        return Recommendation("Apply now", "You're a strong fit. Tailor your resume and apply while the role is fresh.",
                              "green")
    if score >= 70:
        return Recommendation("Apply with a tailored resume",
                              "You meet most requirements. Close the gaps below in your resume and your story.", "blue")
    if score >= 50:
        return Recommendation("Apply with a referral",
                              f"It's a stretch on paper. A referral from someone at {company} and a sharply "
                              "tailored resume matter most here.", "orange")
    return Recommendation("Look at adjacent roles first",
                          "The gaps are significant for this role. The roles below may be a better use of your time.",
                          "gray")


def build_plan(a: JobFitAnalysis, company: str, contacts: list | None = None,
               has_connections: bool = False) -> list[PlanStep]:
    """contacts: ranked referrals.Contact list for this company (best first)."""
    steps = []
    if a.resume_edits:
        steps.append(PlanStep("resume", "resume", f"Tailor your resume ({len(a.resume_edits)} edits)",
                              "Apply the line-by-line suggestions under **Resume** so your resume speaks this "
                              "role's language."))
    # skills_to_build is already ranked by impact on this candidate's chances.
    for i, s in enumerate(a.skills_to_build[:3]):
        steps.append(PlanStep(f"skill-{i}", "skill", f"Build: {s.skill}", s.how))
    if contacts:
        best = contacts[0]
        steps.append(PlanStep("referral", "referral", f"Ask {best.name} for a referral",
                              f"{best.position} at {company}. {best.why}. Draft a message under "
                              "**People you know**."))
    elif has_connections:
        steps.append(PlanStep("referral", "referral", f"Find a path into {company}",
                              "None of your LinkedIn connections work here. Look for alumni from your school or "
                              "past companies, or ask a connection who knows someone on the team."))
    else:
        steps.append(PlanStep("referral", "referral", f"Find a referral at {company}",
                              "Import your LinkedIn connections in **Settings** to see who you know here."))
    if a.what_to_emphasize:
        steps.append(PlanStep("story", "story", "Prepare your story", a.what_to_emphasize[0]))
    steps.append(PlanStep("apply", "apply", "Apply", "Submit your application with the tailored resume."))
    return steps


# --- Adjacent roles --------------------------------------------------------------------

STOPWORDS = {"senior", "sr", "junior", "jr", "lead", "staff", "principal", "head", "associate", "i", "ii", "iii",
             "of", "and", "the", "a", "an", "for", "to", "in", "at", "&", "-", "remote"}


def _words(title: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", title.lower()) if w not in STOPWORDS]


def _contains_phrase(words: list[str], phrase: list[str]) -> bool:
    n = len(phrase)
    return any(words[i:i + n] == phrase for i in range(len(words) - n + 1))


def title_matches(suggested: str, posting_title: str) -> bool:
    """True if a posting is the same kind of job as a suggested title.

    Titles look like "<function>, <specialty>", e.g. "Product Manager, Platform / API".
    The function must appear as a phrase ("Product Marketing Manager" is not a
    "Product Manager"), and if a specialty is given, at least one of its words must too.
    """
    parts = re.split(r"\s*[,|(]\s*", suggested, maxsplit=1)
    function, specialty = _words(parts[0]), set(_words(parts[1])) if len(parts) > 1 else set()
    if not function:
        return False
    have = _words(posting_title)
    return _contains_phrase(have, function) and (not specialty or bool(specialty & set(have)))


def find_adjacent_openings(a: JobFitAnalysis, this_posting: dict, open_postings: list[dict],
                           limit_per_role: int = 4) -> list[tuple[str, str, list[dict]]]:
    """For each adjacent role type: (title, why, matching open postings), same company first."""
    results = []
    for role in a.adjacent_roles:
        matches = [p for p in open_postings
                   if p["id"] != this_posting["posting_id"] and title_matches(role.title, p["title"])]
        matches.sort(key=lambda p: p["company_id"] != this_posting["company_id"])
        results.append((role.title, role.why, matches[:limit_per_role]))
    return results
