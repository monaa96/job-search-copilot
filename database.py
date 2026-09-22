"""SQLite storage for jobs and their analyses.

Jobs and analyses are separate tables so that a job can be re-analyzed later
(e.g. against an updated resume), and so the V2 application tracker can hang
application status off the jobs table.
"""

import json
import sqlite3
from pathlib import Path

from analyzer import JobFitAnalysis

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
