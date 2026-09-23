"""Streamlit UI for the AI Job Search Copilot.

Run with:  streamlit run app.py
"""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

import database
import job_sources
import scout
from analyzer import MODEL, analyze_fit
from discovery import suggest_companies
from search_profile import SearchProfile, load_resume, save_resume
from ui import render_analysis, show_errors

load_dotenv(Path(__file__).parent / ".env")
st.set_page_config(page_title="Job Search Copilot", page_icon="🧭", layout="wide")

# On Streamlit Community Cloud, settings come from the app's Secrets instead of .env.
try:
    for key in ("ANTHROPIC_API_KEY", "DEMO_MODE", "DEMO_PASSCODE"):
        if key in st.secrets and not os.getenv(key):
            os.environ[key] = str(st.secrets[key])
except FileNotFoundError:
    pass  # no secrets file: running locally with .env

# The public deployment runs a restricted demo: nothing is saved and live
# analysis needs a passcode. See demo.py.
if os.getenv("DEMO_MODE", "").lower() == "true":
    import demo
    demo.render()
    st.stop()

database.init_db()


def split_list(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


profile = database.get_profile()
resume_text, resume_pdf = load_resume()
has_resume = bool(resume_text or resume_pdf)

# --- Sidebar: resume -----------------------------------------------------------
with st.sidebar:
    st.header("Your resume")
    if has_resume:
        st.success(f"Resume saved ({'PDF' if resume_pdf else 'text'})")
    with st.expander("Replace resume" if has_resume else "Add your resume", expanded=not has_resume):
        uploaded = st.file_uploader("Upload a PDF or text file", type=["pdf", "txt", "md"])
        pasted = st.text_area("…or paste it here", height=200)
        if st.button("Save resume", disabled=not (uploaded or pasted.strip())):
            if uploaded is not None and uploaded.name.lower().endswith(".pdf"):
                save_resume(pdf=uploaded.getvalue())
            elif uploaded is not None:
                save_resume(text=uploaded.getvalue().decode("utf-8", errors="ignore"))
            else:
                save_resume(text=pasted)
            st.rerun()
    st.caption("Saved on this computer only, never uploaded to GitHub.")

# --- Main area -------------------------------------------------------------------
st.title("🧭 AI Job Search Copilot")

if not has_resume or not profile.interests or not database.list_companies("tracking"):
    st.info(
        "**Getting started:** ① save your resume in the sidebar → ② fill in **My search** → "
        "③ find and approve companies in **Companies** → ④ **Scan now** in **Today's jobs**."
    )

jobs_tab, companies_tab, search_tab, analyze_tab, history_tab = st.tabs(
    ["🔎 Today's jobs", "🏢 Companies", "⚙️ My search", "📝 Analyze a job", "📚 Saved analyses"]
)

# --- Today's jobs ------------------------------------------------------------------
with jobs_tab:
    tracking = database.list_companies("tracking")
    top_left, top_right = st.columns([3, 1])
    last_scan = database.get_last_scan()
    top_left.caption(f"Last scan: {last_scan}" if last_scan else "No scans yet.")
    scan_clicked = top_right.button("Scan now", type="primary", disabled=not (tracking and has_resume),
                                    use_container_width=True)
    if scan_clicked:
        with show_errors(), st.status("Scanning your companies…", expanded=True) as status:
            scout.run_scan(log=st.write)
            status.update(label="Scan complete", state="complete", expanded=False)

    view = st.radio("Show", ["New & saved", "Saved only"], horizontal=True, label_visibility="collapsed")
    show_below = st.checkbox(f"Include jobs scoring below {profile.min_score}")
    statuses = ("saved",) if view == "Saved only" else ("new", "saved")
    postings = database.list_scored_postings(0 if show_below else profile.min_score, statuses)

    if not postings:
        st.write("No jobs to show yet. Run a scan once you're tracking some companies.")
    for p in postings:
        star = "⭐ " if p["status"] == "saved" else ""
        label = f"{star}**{p['fit_score']}** · {p['title']} — {p['company']} · {p['location'] or 'Location not listed'}"
        with st.expander(label):
            st.write(p["fit_reason"])
            st.markdown(f"[View posting ↗]({p['url']})" + (f" · posted {p['posted_at'][:10]}" if p["posted_at"] else ""))

            b1, b2, b3, _ = st.columns([1, 1, 1, 3])
            if p["status"] == "saved":
                if b1.button("Unsave", key=f"unsave-{p['id']}"):
                    database.set_posting_status(p["id"], "new")
                    st.rerun()
            elif b1.button("⭐ Save", key=f"save-{p['id']}"):
                database.set_posting_status(p["id"], "saved")
                st.rerun()
            if b2.button("Dismiss", key=f"dismiss-{p['id']}"):
                database.set_posting_status(p["id"], "dismissed")
                st.rerun()
            if not p["analysis_id"] and b3.button("Full analysis", key=f"analyze-{p['id']}"):
                with show_errors(), st.spinner("Analyzing… (about 30 seconds)"):
                    scout.analyze_posting(p)
                    st.rerun()

            if p["analysis_id"] and (analysis := database.get_analysis(p["analysis_id"])):
                st.divider()
                render_analysis(analysis)

# --- Companies ---------------------------------------------------------------------
with companies_tab:
    st.markdown("Claude researches companies that match **My search**. You approve which ones to track, "
                "and the daily scan checks their job boards.")
    if st.button("🔍 Find companies for me", type="primary", disabled=not profile.interests):
        with show_errors(), st.status("Researching companies… (1–3 minutes)", expanded=True) as status:
            existing = [c["name"] for c in database.list_companies()]
            suggestions = suggest_companies(profile, existing, resume_text, resume_pdf)
            st.write(f"Found {len(suggestions)} companies. Checking which have a public job board…")
            with ThreadPoolExecutor(6) as pool:
                boards = list(pool.map(lambda c: job_sources.find_board(c.name, c.careers_url), suggestions))
            verified = 0
            for company, board in zip(suggestions, boards):
                ats, slug = board or (None, None)
                database.add_company(company.name, company.why_it_fits, ats, slug,
                                     "suggested" if board else "unverified")
                verified += bool(board)
            status.update(label=f"{verified} of {len(suggestions)} companies can be tracked automatically",
                          state="complete", expanded=False)
    if not profile.interests:
        st.caption("Fill in your interests in **My search** first.")

    suggested = database.list_companies("suggested")
    if suggested:
        st.subheader(f"Suggested ({len(suggested)}): approve the ones you want")
        if st.button("Track all suggested"):
            for c in suggested:
                database.set_company_status(c["id"], "tracking")
            st.rerun()
        for c in suggested:
            info, track, skip = st.columns([6, 1, 1])
            info.markdown(f"**{c['name']}** — {c['why_it_fits']}  \n"
                          f"[{c['ats'].title()} job board ↗]({job_sources.board_page_url(c['ats'], c['ats_slug'])})")
            if track.button("Track", key=f"track-{c['id']}"):
                database.set_company_status(c["id"], "tracking")
                st.rerun()
            if skip.button("Skip", key=f"skip-{c['id']}"):
                database.set_company_status(c["id"], "rejected")
                st.rerun()

    st.subheader(f"Tracking ({len(database.list_companies('tracking'))})")
    for c in database.list_companies("tracking"):
        info, stop = st.columns([7, 1])
        info.markdown(f"**{c['name']}** · [{c['ats'].title()} ↗]({job_sources.board_page_url(c['ats'], c['ats_slug'])})"
                      + (f" — {c['why_it_fits']}" if c["why_it_fits"] else ""))
        if stop.button("Stop", key=f"stop-{c['id']}"):
            database.delete_company(c["id"])
            st.rerun()

    with st.expander("➕ Add a company yourself"):
        with st.form("add-company", clear_on_submit=True):
            name = st.text_input("Company name")
            careers_url = st.text_input("Careers page URL (optional, helps find the job board)")
            if st.form_submit_button("Add") and name.strip():
                with st.spinner("Looking for a public job board…"):
                    board = job_sources.find_board(name.strip(), careers_url.strip())
                if board:
                    if database.add_company(name.strip(), "", board[0], board[1], "tracking"):
                        st.success(f"Now tracking {name} ({board[0].title()}).")
                    else:
                        st.warning(f"{name} is already on your list.")
                else:
                    st.error(f"Couldn't find a Greenhouse, Lever or Ashby job board for {name}. "
                             "Try pasting the link from one of their job postings as the careers URL.")

    unverified = database.list_companies("unverified")
    if unverified:
        with st.expander(f"Suggested but not trackable ({len(unverified)})"):
            st.caption("These companies use a hiring system without a public feed (often large companies "
                       "with their own career sites). Check their careers pages yourself.")
            for c in unverified:
                st.markdown(f"**{c['name']}** — {c['why_it_fits']}")

# --- My search ---------------------------------------------------------------------
with search_tab:
    with st.form("profile"):
        interests = st.text_area(
            "Interests and industries",
            value=profile.interests,
            placeholder="e.g. AI developer tools, fintech, climate tech; mission-driven teams; B2B SaaS",
        )
        stage = st.text_input("Company stage / size", value=profile.company_stage,
                              placeholder="e.g. Series B to public, 100–5,000 employees")
        locations = st.text_input("Locations (comma-separated; leave blank for anywhere)",
                                  value=", ".join(profile.locations), placeholder="e.g. New York, Remote")
        include = st.text_input("Job titles to include (comma-separated)", value=", ".join(profile.include_titles),
                                help="A job must contain one of these in its title.")
        exclude = st.text_input("Job titles to exclude (comma-separated)", value=", ".join(profile.exclude_titles))
        min_score = st.slider("Minimum fit score for your daily list", 0, 100, profile.min_score, step=5)
        if st.form_submit_button("Save", type="primary"):
            database.save_profile(SearchProfile(
                interests=interests.strip(), company_stage=stage.strip(), locations=split_list(locations),
                include_titles=split_list(include), exclude_titles=split_list(exclude), min_score=min_score,
            ))
            st.success("Saved. Changes to titles or locations apply on the next scan.")
            st.rerun()

# --- Analyze a single job -------------------------------------------------------------
with analyze_tab:
    job_description = st.text_area("Job description", height=300, placeholder="Paste the full job posting…")

    if st.button("Analyze fit", disabled=not job_description.strip()):
        if not has_resume:
            st.error("Save your resume in the sidebar first.")
        else:
            with show_errors(), st.spinner("Comparing your experience to the role… (this can take a minute)"):
                result = analyze_fit(job_description, resume_text=resume_text, resume_pdf=resume_pdf)
                database.save_analysis(job_description, result, MODEL)
                st.session_state["latest"] = result

    if "latest" in st.session_state:
        st.divider()
        render_analysis(st.session_state["latest"])

# --- Saved analyses -----------------------------------------------------------------
with history_tab:
    saved = database.list_analyses()
    if not saved:
        st.write("No analyses yet.")
    for row in saved:
        label = f"{row['result'].match_score}% · {row['title']} — {row['company']} · {row['created_at'][:10]}"
        with st.expander(label):
            render_analysis(row["result"])
            if st.button("Delete", key=f"delete-{row['id']}"):
                database.delete_analysis(row["id"])
                st.rerun()
