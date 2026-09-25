"""Daily job scan, for every user or just one.

    tracked companies → fetch open jobs once per company (free)
      → each user's keyword filter (free)
      → quick AI fit check on each user's new jobs (cheap, capped per user per day)
      → full analysis on each user's best few (capped per user per day)

Runs from the app's "Scan now" button (one user), or for all users from the
command line / the daily GitHub Actions workflow:
    python scout.py
"""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Callable

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, Field

import database
import job_sources
import limits
from analyzer import MODEL, SCORING_GUIDE, analyze_fit, resume_block

PARALLEL_REQUESTS = 6


class QuickFit(BaseModel):
    score: int = Field(description="Overall fit from 0 to 100")
    reason: str = Field(description="One sentence naming the deciding factor")


QUICK_FIT_SYSTEM = """You screen job postings for a candidate. Given their resume and one \
job posting, estimate how well they fit. Judge what the job actually requires against what \
the candidate has done, not keyword overlap, and be candid rather than generous. The \
reason is shown to the candidate, so address them as "you".

""" + SCORING_GUIDE


def _posting_text(p: dict) -> str:
    return (f"<job_posting>\nTitle: {p['title']}\nCompany: {p['company']}\n"
            f"Location: {p['location']}\n\n{p['description']}\n</job_posting>")


def _has_resume(user: dict) -> bool:
    return bool(user["resume_pdf"] or user["resume_text"])


def quick_fit(client: anthropic.Anthropic, posting: dict, user: dict) -> QuickFit | None:
    resume = resume_block(user["resume_text"], user["resume_pdf"])
    # The resume is identical on every call for this user, so cache it.
    resume["cache_control"] = {"type": "ephemeral"}
    response = client.messages.parse(
        model=MODEL,
        max_tokens=4000,
        system=QUICK_FIT_SYSTEM,
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": [resume, {"type": "text", "text": _posting_text(posting)}]}],
        output_format=QuickFit,
    )
    if response.stop_reason in ("refusal", "max_tokens"):
        return None
    return response.parsed_output


def analyze_posting(user: dict, posting: dict, client: anthropic.Anthropic | None = None) -> int:
    """Run the full fit analysis on one of a user's postings. Returns the analysis id."""
    limits.require(user, "analyses")
    result = analyze_fit(_posting_text(posting), resume_text=user["resume_text"],
                         resume_pdf=user["resume_pdf"], client=client)
    limits.use(user, "analyses")
    analysis_id = database.save_analysis(user["id"], _posting_text(posting), result, MODEL)
    database.set_posting_analysis(posting["id"], analysis_id)
    # The full analysis is the more careful judgment, so its score replaces the quick one.
    database.set_fit(posting["id"], result.match_score, posting["fit_reason"] or result.verdict)
    return analysis_id


def run_scan(user_ids: list[int] | None = None, log: Callable[[str], None] = print,
             auto_analyze: bool = True) -> dict[int, str]:
    """Scan tracked companies for the given users (default: everyone).

    auto_analyze: also run full analyses on each user's top matches. The app
    turns this off so an on-demand scan returns quickly.

    Returns {user_id: one-line summary}.
    """
    database.init_db()
    all_users = [database.get_user(uid) for uid in (user_ids or database.list_user_ids())]
    users = {u["id"]: u for u in all_users if u and _has_resume(u)}
    profiles = {uid: database.get_profile(u) for uid, u in users.items()}
    companies = database.tracked_companies(list(users))
    if not companies:
        raise RuntimeError("No tracked companies to scan. Add some in the Companies tab.")

    # 1. Fetch each company once and apply each user's filter (no AI, no cost).
    new_counts = {uid: 0 for uid in users}
    for company in companies.values():
        try:
            jobs = job_sources.fetch_jobs(company["ats"], company["ats_slug"])
        except Exception as e:
            log(f"Warning: {company['name']}: couldn't fetch jobs ({e})")
            continue
        matches = {uid: [j for j in jobs if profiles[uid].matches(j["title"], j["location"])]
                   for uid in company["user_ids"] if uid in users}
        keep = {j["external_id"] for matched in matches.values() for j in matched}
        posting_ids = database.upsert_postings(company["id"], jobs, keep)
        for uid, matched in matches.items():
            added = database.add_user_postings(uid, [posting_ids[j["external_id"]] for j in matched])
            new_counts[uid] += added
        log(f"{company['name']}: {len(jobs)} open jobs")

    # 2. Quick fit check on each user's new matches, within their daily limit.
    client = anthropic.Anthropic()
    tasks = []
    for uid, user in users.items():
        batch = database.postings_needing_fit_check(uid, limits.remaining(user, "fit_checks"))
        tasks += [(user, p) for p in batch]
    if tasks:
        log(f"Checking fit for {len(tasks)} new jobs…")

    def check(task):
        user, p = task
        try:
            return user, p, quick_fit(client, p, user), None
        except anthropic.APIError as e:
            return user, p, None, e

    # Results are handled here, on the main thread, because the UI's log
    # can't be written to from worker threads.
    with ThreadPoolExecutor(PARALLEL_REQUESTS) as pool:
        for user, p, fit, error in pool.map(check, tasks):
            if error:
                log(f"Warning: Fit check failed for {p['title']} at {p['company']}: {error}")
                continue
            limits.use(user, "fit_checks")
            if fit:
                database.set_fit(p["id"], max(0, min(100, fit.score)), fit.reason)

    # 3. Full analysis on each user's strongest new matches, then summarize.
    summaries = {}
    for uid, user in users.items():
        profile = profiles[uid]
        top = [p for p in database.list_scored_postings(uid, profile.min_score, ("new",)) if not p["analysis_id"]]
        budget = min(limits.AUTO_ANALYSES_PER_SCAN[limits.is_owner(user)], limits.remaining(user, "analyses"))
        budget = budget if auto_analyze else 0
        for p in top[:budget]:
            log(f"Full analysis: {p['title']} at {p['company']} ({p['fit_score']})")
            try:
                analyze_posting(user, p, client)
            except Exception as e:
                log(f"Warning: Full analysis failed for {p['title']}: {e}")

        in_list = len(database.list_scored_postings(uid, profile.min_score, ("new",)))
        waiting = database.count_postings_needing_fit_check(uid)
        summary = (f"{datetime.now():%b %d, %I:%M %p} · {new_counts[uid]} new roles, "
                   f"{in_list} at {profile.min_score}+")
        if waiting:
            summary += f" · {waiting} more to score next scan"
        database.set_last_scan(uid, summary)
        summaries[uid] = summary
    log(f"Scan finished for {len(users)} user(s).")
    return summaries


def notify(message: str) -> None:
    """Show a macOS notification (no-op elsewhere, e.g. in GitHub Actions)."""
    import subprocess
    import sys
    if sys.platform == "darwin":
        script = f"display notification {json.dumps(message)} with title \"Job Search Copilot\""
        subprocess.run(["osascript", "-e", script], check=False)


if __name__ == "__main__":
    load_dotenv(Path(__file__).parent / ".env")
    try:
        results = run_scan()
        notify(next(iter(results.values())) if len(results) == 1 else f"Scanned jobs for {len(results)} users")
    except Exception as e:
        notify(f"Daily scan failed: {e}")
        raise
