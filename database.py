"""Storage for users, companies, job postings and analyses.

Runs on SQLite locally (data/copilot.db) and on Postgres in the cloud: set
DATABASE_URL to switch. Companies and postings are shared across users, so
each company's job board is fetched once per scan no matter how many users
track it; everything personal (resume, search, statuses, scores) is per user.
"""

import os
from datetime import date
from pathlib import Path

from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Integer, LargeBinary, MetaData, String, Table, Text,
    UniqueConstraint, create_engine, delete, func, select, true, update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine

from analyzer import JobFitAnalysis
from search_profile import SearchProfile

DATA_DIR = Path(__file__).parent / "data"

metadata = MetaData()

users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True),
    Column("email", String(320), nullable=False, unique=True),
    Column("name", String(200), nullable=False, server_default=""),
    Column("resume_pdf", LargeBinary),
    Column("resume_text", Text),
    Column("profile_json", Text),
    Column("last_scan", Text),
    Column("created_at", DateTime, server_default=func.now()),
)

# Shared across users: one row per company job board.
companies = Table(
    "companies", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(200), nullable=False),
    Column("ats", String(20), nullable=False),
    Column("ats_slug", String(200), nullable=False),
    UniqueConstraint("ats", "ats_slug"),
)

# A user's relationship to a company.
# status: suggested (awaiting approval) | tracking | rejected | unverified (no job feed found)
user_companies = Table(
    "user_companies", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("company_id", Integer, ForeignKey("companies.id", ondelete="CASCADE")),
    Column("name", String(200), nullable=False),  # also covers unverified companies with no board
    Column("why_it_fits", Text, nullable=False, server_default=""),
    Column("status", String(20), nullable=False),
    UniqueConstraint("user_id", "name"),
)

# Shared: every job seen on a tracked board. The description is kept only for
# jobs that pass at least one user's filters.
postings = Table(
    "postings", metadata,
    Column("id", Integer, primary_key=True),
    Column("company_id", Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
    Column("external_id", String(200), nullable=False),
    Column("title", Text, nullable=False),
    Column("location", Text, nullable=False, server_default=""),
    Column("url", Text, nullable=False, server_default=""),
    Column("description", Text),
    Column("posted_at", String(40)),
    Column("is_open", Boolean, nullable=False, server_default=true()),
    UniqueConstraint("company_id", "external_id"),
)

# A posting that matched a user's filters. status: new | saved | dismissed
user_postings = Table(
    "user_postings", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("posting_id", Integer, ForeignKey("postings.id", ondelete="CASCADE"), nullable=False),
    Column("status", String(20), nullable=False, server_default="new"),
    Column("fit_score", Integer),
    Column("fit_reason", Text),
    Column("analysis_id", Integer, ForeignKey("analyses.id", ondelete="SET NULL")),
    Column("first_seen", DateTime, server_default=func.now()),
    UniqueConstraint("user_id", "posting_id"),
)

analyses = Table(
    "analyses", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("title", Text, nullable=False),
    Column("company", Text, nullable=False),
    Column("job_description", Text, nullable=False),
    Column("match_score", Integer, nullable=False),
    Column("result_json", Text, nullable=False),
    Column("model", String(100), nullable=False),
    Column("created_at", DateTime, server_default=func.now()),
)

# Per-user daily counters for rate limits.
usage = Table(
    "usage", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("day", Date, nullable=False),
    Column("kind", String(30), nullable=False),
    Column("count", Integer, nullable=False, server_default="0"),
    UniqueConstraint("user_id", "day", "kind"),
)

_engine: Engine | None = None


def engine() -> Engine:
    global _engine
    if _engine is None:
        url = os.getenv("DATABASE_URL")
        if url:
            # Hosted Postgres services hand out postgres:// URLs; SQLAlchemy needs the driver named.
            url = url.replace("postgres://", "postgresql://", 1).replace("postgresql://", "postgresql+psycopg://", 1)
            _engine = create_engine(url, pool_pre_ping=True)
        else:
            DATA_DIR.mkdir(exist_ok=True)
            _engine = create_engine(f"sqlite:///{DATA_DIR / 'copilot.db'}")
            from sqlalchemy import event

            @event.listens_for(_engine, "connect")
            def _fk_on(dbapi_conn, _):
                dbapi_conn.execute("PRAGMA foreign_keys = ON")
        # Create any missing tables in whichever database we just connected to.
        metadata.create_all(_engine)
    return _engine


def init_db() -> None:
    engine()


def _insert(table):
    """INSERT that supports on_conflict_* on both SQLite and Postgres."""
    return (pg_insert if engine().dialect.name == "postgresql" else sqlite_insert)(table)


# --- Users -------------------------------------------------------------------------

def get_or_create_user(email: str, name: str = "") -> dict:
    with engine().begin() as conn:
        conn.execute(_insert(users).values(email=email.lower(), name=name).on_conflict_do_nothing())
        return dict(conn.execute(select(users).where(users.c.email == email.lower())).mappings().one())


def get_user(user_id: int) -> dict | None:
    with engine().connect() as conn:
        row = conn.execute(select(users).where(users.c.id == user_id)).mappings().first()
    return dict(row) if row else None


def list_user_ids() -> list[int]:
    with engine().connect() as conn:
        return list(conn.execute(select(users.c.id)).scalars())


def delete_user(user_id: int) -> None:
    with engine().begin() as conn:
        conn.execute(delete(users).where(users.c.id == user_id))


def get_profile(user: dict) -> SearchProfile:
    return SearchProfile.model_validate_json(user["profile_json"]) if user.get("profile_json") else SearchProfile()


def save_profile(user_id: int, profile: SearchProfile) -> None:
    with engine().begin() as conn:
        conn.execute(update(users).where(users.c.id == user_id).values(profile_json=profile.model_dump_json()))


def save_resume(user_id: int, pdf: bytes | None = None, text: str | None = None) -> None:
    with engine().begin() as conn:
        conn.execute(update(users).where(users.c.id == user_id).values(resume_pdf=pdf, resume_text=None if pdf else text))


def set_last_scan(user_id: int, summary: str) -> None:
    with engine().begin() as conn:
        conn.execute(update(users).where(users.c.id == user_id).values(last_scan=summary))


# --- Usage limits --------------------------------------------------------------

def get_usage(user_id: int, kind: str) -> int:
    with engine().connect() as conn:
        return conn.execute(select(usage.c.count).where(
            usage.c.user_id == user_id, usage.c.day == date.today(), usage.c.kind == kind)).scalar() or 0


def add_usage(user_id: int, kind: str, n: int = 1) -> None:
    with engine().begin() as conn:
        stmt = _insert(usage).values(user_id=user_id, day=date.today(), kind=kind, count=n)
        conn.execute(stmt.on_conflict_do_update(
            index_elements=["user_id", "day", "kind"], set_={"count": usage.c.count + n}))


# --- Analyses ----------------------------------------------------------------------

def save_analysis(user_id: int, job_description: str, analysis: JobFitAnalysis, model: str) -> int:
    with engine().begin() as conn:
        return conn.execute(analyses.insert().values(
            user_id=user_id, title=analysis.job_title, company=analysis.company, job_description=job_description,
            match_score=analysis.match_score, result_json=analysis.model_dump_json(), model=model,
        )).inserted_primary_key[0]


def list_analyses(user_id: int) -> list[dict]:
    with engine().connect() as conn:
        rows = conn.execute(select(analyses).where(analyses.c.user_id == user_id)
                            .order_by(analyses.c.created_at.desc(), analyses.c.id.desc())).mappings().all()
    return [{**dict(r), "result": JobFitAnalysis.model_validate_json(r["result_json"])} for r in rows]


def get_analysis(user_id: int, analysis_id: int) -> JobFitAnalysis | None:
    with engine().connect() as conn:
        raw = conn.execute(select(analyses.c.result_json).where(
            analyses.c.id == analysis_id, analyses.c.user_id == user_id)).scalar()
    return JobFitAnalysis.model_validate_json(raw) if raw else None


def delete_analysis(user_id: int, analysis_id: int) -> None:
    with engine().begin() as conn:
        conn.execute(delete(analyses).where(analyses.c.id == analysis_id, analyses.c.user_id == user_id))


# --- Companies -----------------------------------------------------------------------

def upsert_company(name: str, ats: str, ats_slug: str) -> int:
    with engine().begin() as conn:
        conn.execute(_insert(companies).values(name=name, ats=ats, ats_slug=ats_slug).on_conflict_do_nothing())
        return conn.execute(select(companies.c.id).where(
            companies.c.ats == ats, companies.c.ats_slug == ats_slug)).scalar_one()


def add_user_company(user_id: int, name: str, why_it_fits: str, company_id: int | None, status: str) -> bool:
    """Returns False if the user already has a company with this name."""
    with engine().begin() as conn:
        existing = conn.execute(select(user_companies.c.id).where(
            user_companies.c.user_id == user_id, func.lower(user_companies.c.name) == name.lower())).first()
        if existing:
            return False
        conn.execute(user_companies.insert().values(
            user_id=user_id, name=name, why_it_fits=why_it_fits, company_id=company_id, status=status))
        return True


def list_user_companies(user_id: int, status: str | None = None) -> list[dict]:
    query = (select(user_companies, companies.c.ats, companies.c.ats_slug)
             .select_from(user_companies.outerjoin(companies, companies.c.id == user_companies.c.company_id))
             .where(user_companies.c.user_id == user_id).order_by(user_companies.c.name))
    if status:
        query = query.where(user_companies.c.status == status)
    with engine().connect() as conn:
        return [dict(r) for r in conn.execute(query).mappings()]


def set_user_company_status(user_id: int, row_id: int, status: str) -> None:
    with engine().begin() as conn:
        conn.execute(update(user_companies).where(
            user_companies.c.id == row_id, user_companies.c.user_id == user_id).values(status=status))


def delete_user_company(user_id: int, row_id: int) -> None:
    with engine().begin() as conn:
        conn.execute(delete(user_companies).where(user_companies.c.id == row_id, user_companies.c.user_id == user_id))


def tracked_companies(user_ids: list[int]) -> dict[int, dict]:
    """Companies tracked by any of these users: {company_id: {..., "user_ids": [...]}}."""
    query = (select(companies, user_companies.c.user_id)
             .join(user_companies, user_companies.c.company_id == companies.c.id)
             .where(user_companies.c.status == "tracking", user_companies.c.user_id.in_(user_ids)))
    result: dict[int, dict] = {}
    with engine().connect() as conn:
        for r in conn.execute(query).mappings():
            entry = result.setdefault(r["id"], {"id": r["id"], "name": r["name"], "ats": r["ats"],
                                                "ats_slug": r["ats_slug"], "user_ids": []})
            entry["user_ids"].append(r["user_id"])
    return result


# --- Postings ------------------------------------------------------------------------

def upsert_postings(company_id: int, jobs: list[dict], keep_description: set[str]) -> dict[str, int]:
    """Insert or refresh a company's open jobs and mark the rest closed.

    keep_description: external ids whose description should be stored.
    Returns {external_id: posting_id}.
    """
    with engine().begin() as conn:
        for job in jobs:
            values = {k: job[k] for k in ("title", "location", "url", "posted_at")}
            values["is_open"] = True
            if job["external_id"] in keep_description:
                values["description"] = job["description"]
            stmt = _insert(postings).values(company_id=company_id, external_id=job["external_id"], **values)
            conn.execute(stmt.on_conflict_do_update(index_elements=["company_id", "external_id"], set_=values))
        ids = dict(conn.execute(select(postings.c.external_id, postings.c.id)
                                .where(postings.c.company_id == company_id)).all())
        open_ids = {j["external_id"] for j in jobs}
        closed = [pid for ext, pid in ids.items() if ext not in open_ids]
        if closed:
            conn.execute(update(postings).where(postings.c.id.in_(closed)).values(is_open=False))
    return ids


def add_user_postings(user_id: int, posting_ids: list[int]) -> int:
    """Add postings to a user's list if not already there. Returns how many were new."""
    if not posting_ids:
        return 0
    with engine().begin() as conn:
        existing = set(conn.execute(select(user_postings.c.posting_id).where(
            user_postings.c.user_id == user_id, user_postings.c.posting_id.in_(posting_ids))).scalars())
        new = [pid for pid in posting_ids if pid not in existing]
        if new:
            conn.execute(user_postings.insert(), [{"user_id": user_id, "posting_id": pid} for pid in new])
    return len(new)


def _user_posting_query(user_id: int):
    return (select(user_postings, postings.c.title, postings.c.location, postings.c.url, postings.c.description,
                   postings.c.posted_at, companies.c.name.label("company"))
            .join(postings, postings.c.id == user_postings.c.posting_id)
            .join(companies, companies.c.id == postings.c.company_id)
            .where(user_postings.c.user_id == user_id, postings.c.is_open.is_(True)))


def postings_needing_fit_check(user_id: int, limit: int) -> list[dict]:
    query = (_user_posting_query(user_id)
             .where(user_postings.c.status == "new", user_postings.c.fit_score.is_(None))
             .order_by(user_postings.c.first_seen.desc()).limit(limit))
    with engine().connect() as conn:
        return [dict(r) for r in conn.execute(query).mappings()]


def count_postings_needing_fit_check(user_id: int) -> int:
    return len(postings_needing_fit_check(user_id, 10_000))


def set_fit(user_posting_id: int, score: int, reason: str) -> None:
    with engine().begin() as conn:
        conn.execute(update(user_postings).where(user_postings.c.id == user_posting_id)
                     .values(fit_score=score, fit_reason=reason))


def set_posting_status(user_id: int, user_posting_id: int, status: str) -> None:
    with engine().begin() as conn:
        conn.execute(update(user_postings).where(
            user_postings.c.id == user_posting_id, user_postings.c.user_id == user_id).values(status=status))


def set_posting_analysis(user_posting_id: int, analysis_id: int) -> None:
    with engine().begin() as conn:
        conn.execute(update(user_postings).where(user_postings.c.id == user_posting_id)
                     .values(analysis_id=analysis_id))


def list_scored_postings(user_id: int, min_score: int, statuses: tuple[str, ...] = ("new", "saved")) -> list[dict]:
    query = (_user_posting_query(user_id)
             .where(user_postings.c.fit_score >= min_score, user_postings.c.status.in_(statuses))
             .order_by(user_postings.c.fit_score.desc(), user_postings.c.first_seen.desc()))
    with engine().connect() as conn:
        return [dict(r) for r in conn.execute(query).mappings()]
