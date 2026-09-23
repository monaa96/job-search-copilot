"""Daily job scan.

    tracked companies → fetch open jobs (free) → keyword filter (free)
      → quick AI fit check on new jobs (cheap) → full analysis on the best few

Run from the app's "Scan now" button, or from the command line:
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
from analyzer import MODEL, SCORING_GUIDE, analyze_fit, resume_block
from search_profile import load_resume

# Caps that keep a single scan's cost predictable. Jobs over the cap wait for
# the next scan rather than being dropped.
MAX_FIT_CHECKS_PER_SCAN = 60
MAX_FULL_ANALYSES_PER_SCAN = 3
PARALLEL_REQUESTS = 4


class QuickFit(BaseModel):
    score: int = Field(description="Overall fit from 0 to 100")
    reason: str = Field(description="One sentence naming the deciding factor")


QUICK_FIT_SYSTEM = """You screen job postings for a candidate. Given their resume and one \
job posting, estimate how well they fit. Judge what the job actually requires against what \
the candidate has done, not keyword overlap, and be candid rather than generous.

""" + SCORING_GUIDE


def _posting_text(p: dict) -> str:
    return (f"<job_posting>\nTitle: {p['title']}\nCompany: {p['company']}\n"
            f"Location: {p['location']}\n\n{p['description']}\n</job_posting>")


def quick_fit(client: anthropic.Anthropic, posting: dict, resume_text, resume_pdf) -> QuickFit | None:
    resume = resume_block(resume_text, resume_pdf)
    # The resume is identical on every call in a scan, so cache it.
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


def analyze_posting(posting: dict, resume_text=None, resume_pdf=None, client=None) -> int:
    """Run the full fit analysis on a posting and link it. Returns the analysis id."""
    if not (resume_text or resume_pdf):
        resume_text, resume_pdf = load_resume()
    result = analyze_fit(_posting_text(posting), resume_text=resume_text, resume_pdf=resume_pdf, client=client)
    analysis_id = database.save_analysis(_posting_text(posting), result, MODEL)
    database.set_posting_analysis(posting["id"], analysis_id)
    return analysis_id


def run_scan(log: Callable[[str], None] = print) -> str:
    """Scan all tracked companies. Returns a one-line summary."""
    database.init_db()
    profile = database.get_profile()
    resume_text, resume_pdf = load_resume()
    if not (resume_text or resume_pdf):
        raise RuntimeError("Save your resume first (sidebar).")
    companies = database.list_companies("tracking")
    if not companies:
        raise RuntimeError("You're not tracking any companies yet. Add some in the Companies tab.")

    # 1. Fetch and filter (no AI, no cost).
    new_count = 0
    for company in companies:
        try:
            jobs = job_sources.fetch_jobs(company["ats"], company["ats_slug"])
        except Exception as e:
            log(f"⚠️ {company['name']}: couldn't fetch jobs ({e})")
            continue
        known = database.get_postings_by_external_id(company["id"])
        company_new = 0
        for job in jobs:
            passes = profile.matches(job["title"], job["location"])
            existing = known.get(job["external_id"])
            if existing is None:
                database.insert_posting(company["id"], job, "new" if passes else "filtered")
                company_new += passes
            elif existing["status"] == "filtered" and passes:
                # Profile changed since we first saw this job; it now qualifies.
                database.refresh_posting(existing["id"], job, status="new")
                company_new += 1
            else:
                database.refresh_posting(existing["id"], job)
        database.mark_closed(company["id"], {j["external_id"] for j in jobs})
        new_count += company_new
        log(f"{company['name']}: {len(jobs)} open jobs, {company_new} new matching your filters")

    # 2. Quick fit check on new matches.
    to_check = database.postings_needing_fit_check(MAX_FIT_CHECKS_PER_SCAN)
    client = anthropic.Anthropic()
    if to_check:
        log(f"Checking fit for {len(to_check)} new jobs…")

        def check(p):
            try:
                return p, quick_fit(client, p, resume_text, resume_pdf), None
            except anthropic.APIError as e:
                return p, None, e

        # Results are handled here, on the main thread, because the UI's log
        # can't be written to from worker threads.
        with ThreadPoolExecutor(PARALLEL_REQUESTS) as pool:
            for p, fit, error in pool.map(check, to_check):
                if error:
                    log(f"⚠️ Fit check failed for {p['title']} at {p['company']}: {error}")
                elif fit:
                    database.set_fit(p["id"], max(0, min(100, fit.score)), fit.reason)
    waiting = database.count_postings_needing_fit_check()
    if waiting:
        log(f"{waiting} more jobs will be checked on the next scan.")

    # 3. Full analysis on the strongest new matches.
    top = [p for p in database.list_scored_postings(profile.min_score, ("new",)) if not p["analysis_id"]]
    top = top[:MAX_FULL_ANALYSES_PER_SCAN]
    for p in top:
        log(f"Full analysis: {p['title']} at {p['company']} ({p['fit_score']})")
        try:
            analyze_posting(p, resume_text, resume_pdf, client)
        except Exception as e:
            log(f"⚠️ Full analysis failed for {p['title']}: {e}")

    above = len(database.list_scored_postings(profile.min_score, ("new",)))
    summary = (f"{datetime.now():%b %d, %I:%M %p}: {len(companies)} companies scanned, "
               f"{new_count} new matching jobs, {above} in your list at {profile.min_score}+")
    database.set_last_scan(summary)
    log(summary)
    return summary


def notify(message: str) -> None:
    """Show a macOS notification (no-op elsewhere)."""
    import subprocess
    import sys
    if sys.platform == "darwin":
        script = f"display notification {json.dumps(message)} with title \"Job Search Copilot\""
        subprocess.run(["osascript", "-e", script], check=False)


if __name__ == "__main__":
    load_dotenv(Path(__file__).parent / ".env")
    try:
        notify(run_scan())
    except Exception as e:
        notify(f"Daily scan failed: {e}")
        raise
