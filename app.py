"""Streamlit UI for the AI Job Search Copilot.

Run with:  streamlit run app.py

With an [auth] section in .streamlit/secrets.toml, users sign in with Google
and each gets their own data. Without one (plain local use), the app runs as a
single local user.
"""

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

import database
import job_sources
import landing
import limits
import scout
from analyzer import MODEL, analyze_fit
from discovery import discover_for_user
from search_profile import SearchProfile
from ui import render_analysis, show_errors

load_dotenv(Path(__file__).parent / ".env")
st.set_page_config(page_title="Job Search Copilot", page_icon="🧭", layout="wide")

# On Streamlit Community Cloud, settings come from the app's Secrets instead of .env.
# Single-user mode is only allowed when there are no secrets at all (plain local
# use); a hosted app without sign-in configured only shows the landing page, so
# visitors can never end up sharing one account.
try:
    for key in ("ANTHROPIC_API_KEY", "DATABASE_URL", "OWNER_EMAILS"):
        if key in st.secrets and not os.getenv(key):
            os.environ[key] = str(st.secrets[key])
    HOSTED, AUTH_ENABLED = True, "auth" in st.secrets
except FileNotFoundError:
    HOSTED, AUTH_ENABLED = False, False



def split_list(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def resume_uploader(user: dict, key: str) -> None:
    uploaded = st.file_uploader("Upload your resume (PDF or text)", type=["pdf", "txt", "md"], key=f"{key}-file")
    pasted = st.text_area("…or paste it here", height=200, key=f"{key}-text")
    if st.button("Save resume", type="primary", disabled=not (uploaded or pasted.strip()), key=f"{key}-save"):
        if uploaded is not None and uploaded.name.lower().endswith(".pdf"):
            database.save_resume(user["id"], pdf=uploaded.getvalue())
        elif uploaded is not None:
            database.save_resume(user["id"], text=uploaded.getvalue().decode("utf-8", errors="ignore"))
        else:
            database.save_resume(user["id"], text=pasted)
        st.rerun()


def search_form(user: dict, profile: SearchProfile, submit_label: str) -> None:
    with st.form("profile"):
        include = st.text_input("Job titles you're looking for (comma-separated)",
                                value=", ".join(profile.include_titles),
                                help="A job must contain one of these in its title, e.g. Product Manager, Product Lead")
        locations = st.text_input("Locations (comma-separated; leave blank for anywhere)",
                                  value=", ".join(profile.locations), placeholder="e.g. New York, Remote")
        interests = st.text_area("Industries and interests", value=profile.interests,
                                 placeholder="e.g. AI developer tools, fintech, climate tech; mission-driven teams")
        stage = st.text_input("Company stage / size", value=profile.company_stage,
                              placeholder="e.g. Series B to public, 100–5,000 employees")
        with st.expander("More options"):
            exclude = st.text_input("Job titles to exclude (comma-separated)", value=", ".join(profile.exclude_titles))
            min_score = st.slider("Minimum fit score for your daily list", 0, 100, profile.min_score, step=5)
        if st.form_submit_button(submit_label, type="primary"):
            database.save_profile(user["id"], SearchProfile(
                interests=interests.strip(), company_stage=stage.strip(), locations=split_list(locations),
                include_titles=split_list(include), exclude_titles=split_list(exclude), min_score=min_score,
            ))
            st.rerun()


def add_company_form(user: dict) -> None:
    with st.form("add-company", clear_on_submit=True):
        name = st.text_input("Company name")
        careers_url = st.text_input("Careers page URL (optional, helps find the job board)")
        if st.form_submit_button("Add") and name.strip():
            with st.spinner("Looking for a public job board…"):
                board = job_sources.find_board(name.strip(), careers_url.strip())
            if board:
                company_id = database.upsert_company(name.strip(), *board)
                if database.add_user_company(user["id"], name.strip(), "", company_id, "tracking"):
                    st.success(f"Now tracking {name} ({board[0].title()}).")
                else:
                    st.warning(f"{name} is already on your list.")
            else:
                st.error(f"Couldn't find a Greenhouse, Lever or Ashby job board for {name}. "
                         "Try pasting the link from one of their job postings as the careers URL.")


def run_discovery(user: dict) -> None:
    with show_errors(), st.status("Researching companies that fit you… (1–3 minutes)", expanded=True) as status:
        trackable, total = discover_for_user(user, log=st.write)
        status.update(label=f"{trackable} of {total} companies can be tracked automatically",
                      state="complete", expanded=False)


def run_scan(user: dict) -> None:
    with show_errors(), st.status("Scanning job boards… (a few minutes the first time)", expanded=True) as status:
        scout.run_scan([user["id"]], log=st.write)
        status.update(label="Scan complete", state="complete", expanded=False)


# --- Public pages -------------------------------------------------------------------------
if st.query_params.get("page") == "privacy":
    st.markdown((Path(__file__).parent / "PRIVACY.md").read_text())
    st.stop()

# --- Who is this? ---------------------------------------------------------------------
if HOSTED and not AUTH_ENABLED:
    landing.render(sign_in_available=False)
    st.stop()
if AUTH_ENABLED:
    if not st.user.is_logged_in:
        landing.render()
        st.stop()
    user = database.get_or_create_user(st.user.email, getattr(st.user, "name", None) or "")
else:
    user = database.get_or_create_user(limits.LOCAL_USER_EMAIL, "Local user")

profile = database.get_profile(user)
has_resume = bool(user["resume_pdf"] or user["resume_text"])
my_companies = database.list_user_companies(user["id"])

# --- Sidebar: account --------------------------------------------------------------------
with st.sidebar:
    st.markdown(f"**{user['name'] or user['email']}**")
    if AUTH_ENABLED:
        st.caption(user["email"])
        st.button("Sign out", on_click=st.logout)

    if has_resume:
        st.success(f"Resume saved ({'PDF' if user['resume_pdf'] else 'text'})")
        with st.expander("Replace resume"):
            resume_uploader(user, "sidebar")

    st.markdown("**Today's usage**")
    for kind, label in [("fit_checks", "Job fit checks"), ("analyses", "Full analyses"),
                        ("discoveries", "Company searches")]:
        st.caption(f"{label}: {limits.remaining(user, kind)} of {limits.daily_limit(user, kind)} left")

    if AUTH_ENABLED:
        with st.expander("Delete my data"):
            st.caption("Permanently deletes your resume, searches, jobs and analyses.")
            if st.checkbox("I understand this can't be undone") and st.button("Delete everything"):
                database.delete_user(user["id"])
                st.logout()

st.title("🧭 AI Job Search Copilot")

# --- First-run setup: resume → search → companies ------------------------------------------
if not has_resume:
    st.subheader("Step 1 of 3: Your resume")
    st.caption("Used only to score jobs for you. You can delete it anytime.")
    resume_uploader(user, "onboarding")
    st.stop()

if not user["profile_json"]:
    st.subheader("Step 2 of 3: What are you looking for?")
    search_form(user, profile, "Continue")
    st.stop()

if not my_companies:
    st.subheader("Step 3 of 3: Companies to watch")
    st.write("Claude will research companies that match your search and background, then check which "
             "have public job boards it can scan daily. You'll approve the list before scanning starts.")
    if st.button("🔍 Find companies for me", type="primary"):
        run_discovery(user)
        st.rerun()
    with st.expander("…or add a company yourself"):
        add_company_form(user)
    st.stop()

# --- Main tabs -------------------------------------------------------------------------------
suggested = database.list_user_companies(user["id"], "suggested")
tracking = database.list_user_companies(user["id"], "tracking")
if suggested and not tracking:
    st.info("**Almost there:** approve the companies you want to watch in the **🏢 Companies** tab, "
            "then click **Scan now** in **🔎 Today's jobs**.")

jobs_tab, companies_tab, match_tab, history_tab, search_tab = st.tabs(
    ["🔎 Today's jobs", "🏢 Companies", "📝 Resume match", "📚 Saved analyses", "⚙️ My search"]
)

with jobs_tab:
    top_left, top_right = st.columns([3, 1])
    top_left.caption(f"Last scan: {user['last_scan']}" if user["last_scan"]
                     else "No scans yet. New jobs are also checked automatically every morning.")
    if top_right.button("Scan now", type="primary", disabled=not tracking, use_container_width=True):
        run_scan(user)
        st.rerun()

    view = st.radio("Show", ["New & saved", "Saved only"], horizontal=True, label_visibility="collapsed")
    show_below = st.checkbox(f"Include jobs scoring below {profile.min_score}")
    statuses = ("saved",) if view == "Saved only" else ("new", "saved")
    postings = database.list_scored_postings(user["id"], 0 if show_below else profile.min_score, statuses)

    if not postings:
        st.write("No jobs to show yet." if tracking else "Track some companies first.")
    for p in postings:
        star = "⭐ " if p["status"] == "saved" else ""
        label = f"{star}**{p['fit_score']}** · {p['title']} — {p['company']} · {p['location'] or 'Location not listed'}"
        with st.expander(label):
            st.write(p["fit_reason"])
            st.markdown(f"[View posting ↗]({p['url']})" + (f" · posted {p['posted_at'][:10]}" if p["posted_at"] else ""))

            b1, b2, b3, _ = st.columns([1, 1, 1, 3])
            if p["status"] == "saved":
                if b1.button("Unsave", key=f"unsave-{p['id']}"):
                    database.set_posting_status(user["id"], p["id"], "new")
                    st.rerun()
            elif b1.button("⭐ Save", key=f"save-{p['id']}"):
                database.set_posting_status(user["id"], p["id"], "saved")
                st.rerun()
            if b2.button("Dismiss", key=f"dismiss-{p['id']}"):
                database.set_posting_status(user["id"], p["id"], "dismissed")
                st.rerun()
            if not p["analysis_id"] and b3.button("Full analysis", key=f"analyze-{p['id']}"):
                with show_errors(), st.spinner("Analyzing… (about 30 seconds)"):
                    scout.analyze_posting(user, p)
                    st.rerun()

            if p["analysis_id"] and (analysis := database.get_analysis(user["id"], p["analysis_id"])):
                st.divider()
                render_analysis(analysis)

with companies_tab:
    if st.button("🔍 Find more companies", disabled=not profile.interests and not profile.include_titles):
        run_discovery(user)
        st.rerun()

    if suggested:
        st.subheader(f"Suggested ({len(suggested)}): approve the ones you want")
        if st.button("Track all suggested"):
            for c in suggested:
                database.set_user_company_status(user["id"], c["id"], "tracking")
            st.rerun()
        for c in suggested:
            info, track, skip = st.columns([6, 1, 1])
            info.markdown(f"**{c['name']}** — {c['why_it_fits']}  \n"
                          f"[{c['ats'].title()} job board ↗]({job_sources.board_page_url(c['ats'], c['ats_slug'])})")
            if track.button("Track", key=f"track-{c['id']}"):
                database.set_user_company_status(user["id"], c["id"], "tracking")
                st.rerun()
            if skip.button("Skip", key=f"skip-{c['id']}"):
                database.set_user_company_status(user["id"], c["id"], "rejected")
                st.rerun()

    st.subheader(f"Tracking ({len(tracking)})")
    for c in tracking:
        info, stop = st.columns([7, 1])
        info.markdown(f"**{c['name']}** · [{c['ats'].title()} ↗]({job_sources.board_page_url(c['ats'], c['ats_slug'])})"
                      + (f" — {c['why_it_fits']}" if c["why_it_fits"] else ""))
        if stop.button("Stop", key=f"stop-{c['id']}"):
            database.delete_user_company(user["id"], c["id"])
            st.rerun()

    with st.expander("➕ Add a company yourself"):
        add_company_form(user)

    unverified = database.list_user_companies(user["id"], "unverified")
    if unverified:
        with st.expander(f"Suggested but not trackable ({len(unverified)})"):
            st.caption("These companies use a hiring system without a public feed (often large companies "
                       "with their own career sites). Check their careers pages yourself.")
            for c in unverified:
                st.markdown(f"**{c['name']}** — {c['why_it_fits']}")

with match_tab:
    st.write("Paste any job description to see how your resume matches, and how to strengthen it for this role.")
    job_description = st.text_area("Job description", height=300, placeholder="Paste the full job posting…")
    if st.button("Analyze match", type="primary", disabled=not job_description.strip()):
        with show_errors(), st.spinner("Comparing your experience to the role… (about 30 seconds)"):
            limits.require(user, "analyses")
            result = analyze_fit(job_description, resume_text=user["resume_text"], resume_pdf=user["resume_pdf"])
            limits.use(user, "analyses")
            database.save_analysis(user["id"], job_description, result, MODEL)
            st.session_state["latest"] = result
    if "latest" in st.session_state:
        st.divider()
        render_analysis(st.session_state["latest"])

with history_tab:
    saved = database.list_analyses(user["id"])
    if not saved:
        st.write("No analyses yet.")
    for row in saved:
        label = f"{row['match_score']}% · {row['title']} — {row['company']} · {str(row['created_at'])[:10]}"
        with st.expander(label):
            render_analysis(row["result"])
            if st.button("Delete", key=f"delete-{row['id']}"):
                database.delete_analysis(user["id"], row["id"])
                st.rerun()

with search_tab:
    search_form(user, profile, "Save")
    st.caption("Changes to titles or locations apply on the next scan.")
