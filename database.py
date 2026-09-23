"""SQLite storage for jobs and their analyses.

Jobs and analyses are separate tables so that a job can be re-analyzed later
(e.g. against an updated resume), and so the V2 application tracker can hang
application status off the jobs table.
"""

import json
import sqlite3
from pathlib import Path

from analyzer import JobFitAnalysis
from search_profile import SearchProfile

DB_PATH = Path(__file__).parent / "copilot.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                title           TEXT NOT NULL,
                company         TEXT NOT NULL,
                description     TEXT NOT NULL,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS analyses (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id          INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                match_score     INTEGER NOT NULL,
                result_json     TEXT NOT NULL,
                model           TEXT NOT NULL,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );

            -- Key/value store for the search profile and last-scan time.
            CREATE TABLE IF NOT EXISTS settings (
                key             TEXT PRIMARY KEY,
                value           TEXT NOT NULL
            );

            -- status: suggested (AI proposed, awaiting approval) | tracking | rejected
            --         | unverified (no public job feed found)
            CREATE TABLE IF NOT EXISTS companies (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL UNIQUE COLLATE NOCASE,
                why_it_fits     TEXT NOT NULL DEFAULT '',
                ats             TEXT,
                ats_slug        TEXT,
                status          TEXT NOT NULL,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );

            -- Every job seen on a tracked board, so each scan only processes new ones.
            -- status: filtered (failed the keyword filter) | new | saved | dismissed
            CREATE TABLE IF NOT EXISTS postings (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id      INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                external_id     TEXT NOT NULL,
                title           TEXT NOT NULL,
                location        TEXT NOT NULL DEFAULT '',
                url             TEXT NOT NULL DEFAULT '',
                description     TEXT,
                posted_at       TEXT,
                first_seen      TEXT NOT NULL DEFAULT (datetime('now')),
                is_open         INTEGER NOT NULL DEFAULT 1,
                status          TEXT NOT NULL,
                fit_score       INTEGER,
                fit_reason      TEXT,
                analysis_id     INTEGER REFERENCES analyses(id) ON DELETE SET NULL,
                UNIQUE (company_id, external_id)
            );
            """
        )


def save_analysis(job_description: str, analysis: JobFitAnalysis, model: str) -> int:
    """Store the job and its analysis. Returns the new analysis id."""
    with _connect() as conn:
        job_id = conn.execute(
            "INSERT INTO jobs (title, company, description) VALUES (?, ?, ?)",
            (analysis.job_title, analysis.company, job_description),
        ).lastrowid
        return conn.execute(
            "INSERT INTO analyses (job_id, match_score, result_json, model) VALUES (?, ?, ?, ?)",
            (job_id, analysis.match_score, analysis.model_dump_json(), model),
        ).lastrowid


def list_analyses() -> list[dict]:
    """Every saved analysis, newest first, with the parsed result attached."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT a.id, a.match_score, a.result_json, a.created_at,
                   j.title, j.company, j.description
            FROM analyses a JOIN jobs j ON j.id = a.job_id
            ORDER BY a.created_at DESC, a.id DESC
            """
        ).fetchall()
    return [
        {**dict(row), "result": JobFitAnalysis.model_validate(json.loads(row["result_json"]))}
        for row in rows
    ]


def delete_analysis(analysis_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM jobs WHERE id = (SELECT job_id FROM analyses WHERE id = ?)",
            (analysis_id,),
        )


def get_analysis(analysis_id: int) -> JobFitAnalysis | None:
    with _connect() as conn:
        row = conn.execute("SELECT result_json FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
    return JobFitAnalysis.model_validate_json(row["result_json"]) if row else None


# --- Settings ----------------------------------------------------------------

def _get_setting(key: str) -> str | None:
    with _connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def _set_setting(key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_profile() -> SearchProfile:
    raw = _get_setting("profile")
    return SearchProfile.model_validate_json(raw) if raw else SearchProfile()


def save_profile(profile: SearchProfile) -> None:
    _set_setting("profile", profile.model_dump_json())


def get_last_scan() -> str | None:
    return _get_setting("last_scan")


def set_last_scan(summary: str) -> None:
    _set_setting("last_scan", summary)


# --- Companies ---------------------------------------------------------------

def add_company(name: str, why_it_fits: str, ats: str | None, ats_slug: str | None, status: str) -> bool:
    """Returns False if a company with this name already exists."""
    with _connect() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO companies (name, why_it_fits, ats, ats_slug, status) VALUES (?, ?, ?, ?, ?)",
            (name, why_it_fits, ats, ats_slug, status),
        )
        return cur.rowcount == 1


def list_companies(status: str | None = None) -> list[dict]:
    query = "SELECT * FROM companies"
    params: tuple = ()
    if status:
        query += " WHERE status = ?"
        params = (status,)
    with _connect() as conn:
        return [dict(r) for r in conn.execute(query + " ORDER BY name", params)]


def set_company_status(company_id: int, status: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE companies SET status = ? WHERE id = ?", (status, company_id))


def delete_company(company_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM companies WHERE id = ?", (company_id,))


# --- Postings ----------------------------------------------------------------

def get_postings_by_external_id(company_id: int) -> dict[str, dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, external_id, status FROM postings WHERE company_id = ?", (company_id,)
        ).fetchall()
    return {r["external_id"]: dict(r) for r in rows}


def insert_posting(company_id: int, job: dict, status: str) -> None:
    # Filtered-out jobs are stored without their description: we only need to
    # remember that we've seen them.
    description = job["description"] if status != "filtered" else None
    with _connect() as conn:
        conn.execute(
            """INSERT INTO postings (company_id, external_id, title, location, url, description, posted_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (company_id, job["external_id"], job["title"], job["location"], job["url"],
             description, job["posted_at"], status),
        )


def refresh_posting(posting_id: int, job: dict, status: str | None = None) -> None:
    """Update a known posting's details, and optionally its status."""
    with _connect() as conn:
        conn.execute(
            """UPDATE postings SET title = ?, location = ?, url = ?, is_open = 1,
                   description = COALESCE(?, description), status = COALESCE(?, status)
               WHERE id = ?""",
            (job["title"], job["location"], job["url"],
             job["description"] if status == "new" else None, status, posting_id),
        )


def mark_closed(company_id: int, open_external_ids: set[str]) -> None:
    with _connect() as conn:
        rows = conn.execute("SELECT id, external_id FROM postings WHERE company_id = ? AND is_open = 1",
                            (company_id,)).fetchall()
        closed = [r["id"] for r in rows if r["external_id"] not in open_external_ids]
        conn.executemany("UPDATE postings SET is_open = 0 WHERE id = ?", [(i,) for i in closed])


def postings_needing_fit_check(limit: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT p.*, c.name AS company FROM postings p JOIN companies c ON c.id = p.company_id
               WHERE p.status = 'new' AND p.is_open = 1 AND p.fit_score IS NULL
               ORDER BY p.first_seen DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def count_postings_needing_fit_check() -> int:
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM postings WHERE status = 'new' AND is_open = 1 AND fit_score IS NULL"
        ).fetchone()[0]


def set_fit(posting_id: int, score: int, reason: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE postings SET fit_score = ?, fit_reason = ? WHERE id = ?", (score, reason, posting_id))


def set_posting_status(posting_id: int, status: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE postings SET status = ? WHERE id = ?", (status, posting_id))


def set_posting_analysis(posting_id: int, analysis_id: int) -> None:
    with _connect() as conn:
        conn.execute("UPDATE postings SET analysis_id = ? WHERE id = ?", (analysis_id, posting_id))


def list_scored_postings(min_score: int, statuses: tuple[str, ...] = ("new", "saved")) -> list[dict]:
    placeholders = ",".join("?" * len(statuses))
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT p.*, c.name AS company FROM postings p JOIN companies c ON c.id = p.company_id
                WHERE p.is_open = 1 AND p.fit_score >= ? AND p.status IN ({placeholders})
                ORDER BY p.fit_score DESC, p.first_seen DESC""",
            (min_score, *statuses),
        ).fetchall()
    return [dict(r) for r in rows]
