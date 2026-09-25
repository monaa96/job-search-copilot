"""Streamlit UI for the AI Job Search Copilot.

Run with:  streamlit run app.py

With an [auth] section in .streamlit/secrets.toml, users sign in with Google
and each gets their own data. Without any secrets (plain local use), the app
runs as a single local user.
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
import styles
from analyzer import MODEL, analyze_fit
from discovery import discover_for_user
from search_profile import SearchProfile
from ui import fit_badge, fit_label, page_header, render_analysis, safe, show_errors

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
st.set_page_config(page_title="Job Search Copilot", page_icon=str(ROOT / "static" / "icon.svg"), layout="wide")
st.logo(str(ROOT / "static" / "logo.svg"), size="large")
styles.apply()

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


# --- Public pages ------------------------------------------------------------------------
if st.query_params.get("page") == "privacy":
    _, center, _ = st.columns([1, 4, 1])
    center.markdown((ROOT / "PRIVACY.md").read_text())
    st.stop()

# --- Who is this? --------------------------------------------------------------------------
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


# --- Shared pieces -------------------------------------------------------------------------

def split_list(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def resume_uploader(key: str) -> None:
    uploaded = st.file_uploader("Upload your resume (PDF or text)", type=["pdf", "txt", "md"], key=f"{key}-file")
    pasted = st.text_area("Or paste it", height=180, key=f"{key}-text")
    if st.button("Save resume", type="primary", disabled=not (uploaded or pasted.strip()), key=f"{key}-save"):
        if uploaded is not None and uploaded.name.lower().endswith(".pdf"):
            database.save_resume(user["id"], pdf=uploaded.getvalue())
        elif uploaded is not None:
            database.save_resume(user["id"], text=uploaded.getvalue().decode("utf-8", errors="ignore"))
        else:
            database.save_resume(user["id"], text=pasted)
        st.rerun()


def search_form(submit_label: str) -> None:
    with st.form("profile", border=False):
        include = st.text_input("Job titles", value=", ".join(profile.include_titles),
                                help="Comma-separated. A role must contain one of these in its title.",
                                placeholder="e.g. Product Manager, Product Lead")
        locations = st.text_input("Locations", value=", ".join(profile.locations),
                                  help="Comma-separated. Leave blank for anywhere.", placeholder="e.g. New York, Remote")
        interests = st.text_area("Industries and interests", value=profile.interests, height=90,
                                 placeholder="e.g. AI developer tools, fintech, climate tech")
        stage = st.text_input("Company stage or size", value=profile.company_stage,
                              placeholder="e.g. Series B to public")
        with st.expander("More options"):
            exclude = st.text_input("Exclude titles containing", value=", ".join(profile.exclude_titles))
            min_score = st.slider("Minimum fit score to show", 0, 100, profile.min_score, step=5)
        if st.form_submit_button(submit_label, type="primary"):
            database.save_profile(user["id"], SearchProfile(
                interests=interests.strip(), company_stage=stage.strip(), locations=split_list(locations),
                include_titles=split_list(include), exclude_titles=split_list(exclude), min_score=min_score,
            ))
            st.rerun()


def add_company_form() -> None:
    with st.form("add-company", clear_on_submit=True, border=False):
        name = st.text_input("Company name")
        careers_url = st.text_input("Careers page URL (optional)", help="Helps find the company's job board.")
        if st.form_submit_button("Add company") and name.strip():
            with st.spinner("Looking for a public job board…"):
                board = job_sources.find_board(name.strip(), careers_url.strip())
            if board:
                company_id = database.upsert_company(name.strip(), *board)
                if database.add_user_company(user["id"], name.strip(), "", company_id, "tracking"):
                    st.success(f"Now tracking {name}.")
                else:
                    st.warning(f"{name} is already on your list.")
            else:
                st.error(f"Couldn't find a job board for {name}. We support companies hiring through "
                         "Greenhouse, Lever or Ashby. Try pasting a link to one of their job postings.")


def find_roles() -> None:
    """Research companies, track every one with a job board, and scan them for roles."""
    with show_errors(), st.status("Finding roles for you… this takes a few minutes", expanded=True) as status:
        if not database.list_user_companies(user["id"], "suggested"):
            st.write("Researching companies that match your search and background…")
            discover_for_user(user, log=st.write)
        for c in database.list_user_companies(user["id"], "suggested"):
            database.set_user_company_status(user["id"], c["id"], "tracking")
        st.write("Scanning their job boards and scoring each role against your resume…")
        scout.run_scan([user["id"]], log=st.write, auto_analyze=False)
        status.update(label="Done", state="complete", expanded=False)


def refresh_roles() -> None:
    with show_errors(), st.status("Checking for new roles…", expanded=True) as status:
        scout.run_scan([user["id"]], log=st.write, auto_analyze=False)
        status.update(label="Up to date", state="complete", expanded=False)


# --- First-run setup ------------------------------------------------------------------------

def onboarding() -> None:
    step = 1 if not has_resume else 2 if not user["profile_json"] else 3
    _, center, _ = st.columns([1, 3, 1])
    with center:
        st.space("small")
        st.caption(f"STEP {step} OF 3")
        st.progress(step / 3)
        if step == 1:
            st.markdown("## Start with your resume")
            st.caption("It's used only to score roles for you, and you can delete it anytime.")
            resume_uploader("onboarding")
        elif step == 2:
            st.markdown("## What are you looking for?")
            st.caption("Titles and locations filter roles. Interests help find the right companies.")
            search_form("Continue")
        else:
            st.markdown("## Let's find your roles")
            st.markdown("We'll research companies that match your search and background, check their job "
                        "boards, and rank every open role by how well it fits you.")
            if st.button("Find roles for me", type="primary", icon=":material/travel_explore:"):
                find_roles()
                st.rerun()
            with st.expander("Or start with companies you already have in mind"):
                add_company_form()
                if database.list_user_companies(user["id"], "tracking"):
                    if st.button("Scan these companies"):
                        refresh_roles()
                        st.rerun()


# --- Pages ------------------------------------------------------------------------------------

def roles_page() -> None:
    tracking = database.list_user_companies(user["id"], "tracking")
    header, action = st.columns([4, 1], vertical_alignment="bottom")
    with header:
        page_header("Roles for you", user["last_scan"] and f"Last updated {user['last_scan']}"
                    or "Updated automatically every morning", eyebrow="Your daily shortlist")
    if action.button("Check for new roles", icon=":material/refresh:", disabled=not tracking,
                     use_container_width=True):
        refresh_roles()
        st.rerun()

    suggested = database.list_user_companies(user["id"], "suggested")
    if suggested and not tracking:
        with st.container(border=True):
            st.markdown(f"**We found {len(suggested)} companies that match you.** Scan them to see open roles.")
            if st.button("Find roles at these companies", type="primary"):
                find_roles()
                st.rerun()
        return

    all_roles = database.list_scored_postings(user["id"], 0, ("new", "saved"))
    strong = [p for p in all_roles if p["fit_score"] >= profile.min_score]
    metrics = [("blue", f"Roles at {profile.min_score}+", len(strong)),
               ("green", "Saved", sum(p["status"] == "saved" for p in all_roles)),
               ("violet", "Companies watched", len(tracking))]
    for col, (color, label, value) in zip(st.columns(3), metrics):
        with col, st.container(key=f"metric-{color}"):
            st.metric(label, value)

    view = st.segmented_control("View", ["Best matches", "Saved", "All roles"], default="Best matches",
                                label_visibility="collapsed")
    if view == "Saved":
        roles = [p for p in all_roles if p["status"] == "saved"]
    elif view == "All roles":
        roles = all_roles
    else:
        roles = strong

    if not roles:
        if view == "Best matches" and all_roles:
            st.info(f"No roles scored {profile.min_score}+ yet. {len(all_roles)} lower-scoring roles are "
                    "under **All roles**, or you can lower the threshold in **Settings**.")
        else:
            st.caption("Nothing here yet.")
    for p in roles:
        role_card(p)


def role_card(p: dict) -> None:
    _, color = fit_label(p["fit_score"])
    with st.container(border=True, key=f"role-{color}-{p['id']}"):
        info, actions = st.columns([5, 2], vertical_alignment="top")
        with info:
            st.markdown(f"**{safe(p['title'])}**")
            meta = [p["company"], p["location"] or "Location not listed"]
            if p["posted_at"]:
                meta.append(f"Posted {p['posted_at'][:10]}")
            st.caption(" · ".join(meta))
            fit_badge(p["fit_score"])
            st.markdown(safe(p["fit_reason"]))
        with actions, st.container(horizontal=True, horizontal_alignment="right", gap="small"):
            st.link_button("View", p["url"], icon=":material/open_in_new:")
            if p["status"] == "saved":
                if st.button("Saved", key=f"unsave-{p['id']}", icon=":material/bookmark:", type="primary"):
                    database.set_posting_status(user["id"], p["id"], "new")
                    st.rerun()
            elif st.button("Save", key=f"save-{p['id']}", icon=":material/bookmark_border:"):
                database.set_posting_status(user["id"], p["id"], "saved")
                st.rerun()
            if st.button("", key=f"dismiss-{p['id']}", icon=":material/close:", help="Not interested"):
                database.set_posting_status(user["id"], p["id"], "dismissed")
                st.rerun()

        if p["analysis_id"] and (analysis := database.get_analysis(user["id"], p["analysis_id"])):
            with st.expander("Full analysis and resume suggestions"):
                render_analysis(analysis, heading=False)
        elif st.button("Get full analysis and resume suggestions", key=f"analyze-{p['id']}",
                       icon=":material/auto_awesome:", type="tertiary"):
            with show_errors(), st.spinner("Analyzing… about 30 seconds"):
                scout.analyze_posting(user, p)
                st.rerun()


def companies_page() -> None:
    header, action = st.columns([4, 1], vertical_alignment="bottom")
    with header:
        page_header("Companies", "The companies whose job boards are checked for you every morning.",
                    eyebrow="Your watchlist")
    if action.button("Find more", icon=":material/travel_explore:", use_container_width=True):
        with show_errors(), st.status("Researching companies… 1 to 3 minutes", expanded=True) as status:
            discover_for_user(user, log=st.write)
            status.update(label="Done", state="complete", expanded=False)
        st.rerun()

    suggested = database.list_user_companies(user["id"], "suggested")
    if suggested:
        with st.container(border=True):
            top, all_btn = st.columns([4, 1], vertical_alignment="center")
            top.markdown(f"**{len(suggested)} new suggestions**")
            if all_btn.button("Add all", use_container_width=True):
                for c in suggested:
                    database.set_user_company_status(user["id"], c["id"], "tracking")
                st.rerun()
            for c in suggested:
                company_row(c, suggested=True)

    tracking = database.list_user_companies(user["id"], "tracking")
    st.markdown(f"#### Watching ({len(tracking)})")
    for c in tracking:
        company_row(c)

    with st.expander("Add a company"):
        add_company_form()

    unverified = database.list_user_companies(user["id"], "unverified")
    if unverified:
        with st.expander(f"Can't be tracked automatically ({len(unverified)})"):
            st.caption("These companies don't publish a job feed we can read, often because they run their "
                       "own career sites. Check their careers pages directly.")
            for c in unverified:
                st.markdown(f"**{c['name']}**  \n{safe(c['why_it_fits'])}")


def company_row(c: dict, suggested: bool = False) -> None:
    info, actions = st.columns([6, 2], vertical_alignment="center")
    board = job_sources.board_page_url(c["ats"], c["ats_slug"])
    info.markdown(f"**{c['name']}** · [Job board]({board})"
                  + (f"  \n:gray[{safe(c['why_it_fits'])}]" if c["why_it_fits"] else ""))
    with actions, st.container(horizontal=True, horizontal_alignment="right", gap="small"):
        if suggested:
            if st.button("Add", key=f"track-{c['id']}", type="primary"):
                database.set_user_company_status(user["id"], c["id"], "tracking")
                st.rerun()
            if st.button("Skip", key=f"skip-{c['id']}"):
                database.set_user_company_status(user["id"], c["id"], "rejected")
                st.rerun()
        elif st.button("Remove", key=f"stop-{c['id']}"):
            database.delete_user_company(user["id"], c["id"])
            st.rerun()


def match_page() -> None:
    page_header("Resume match", "Paste any job description to see how you match and how to tailor your resume.",
                eyebrow="Tailor your application")
    job_description = st.text_area("Job description", height=260, placeholder="Paste the full job posting…",
                                   label_visibility="collapsed")
    if st.button("Analyze", type="primary", icon=":material/auto_awesome:", disabled=not job_description.strip()):
        with show_errors(), st.spinner("Comparing your experience to the role… about 30 seconds"):
            limits.require(user, "analyses")
            result = analyze_fit(job_description, resume_text=user["resume_text"], resume_pdf=user["resume_pdf"])
            limits.use(user, "analyses")
            database.save_analysis(user["id"], job_description, result, MODEL)
            st.session_state["latest"] = result
    if "latest" in st.session_state:
        with st.container(border=True):
            render_analysis(st.session_state["latest"])


def saved_analyses_page() -> None:
    page_header("Analyses", "Every full analysis you've run.")
    saved = database.list_analyses(user["id"])
    if not saved:
        st.caption("No analyses yet. Run one from a role or from Resume match.")
    for row in saved:
        with st.expander(f"{row['title']} · {row['company']} · {row['match_score']}"):
            render_analysis(row["result"], heading=False)
            if st.button("Delete", key=f"delete-{row['id']}", type="tertiary", icon=":material/delete:"):
                database.delete_analysis(user["id"], row["id"])
                st.rerun()


def settings_page() -> None:
    page_header("Settings")
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.markdown("#### Your search")
        search_form("Save changes")
        st.caption("Title and location changes apply on the next update.")
    with right:
        st.markdown("#### Account")
        with st.container(border=True):
            st.markdown(f"**{user['name'] or 'Signed in'}**  \n:gray[{user['email']}]")
            if AUTH_ENABLED:
                st.button("Sign out", on_click=st.logout, icon=":material/logout:")

        st.markdown("#### Resume")
        with st.container(border=True):
            st.markdown(f"Saved as {'PDF' if user['resume_pdf'] else 'text'}")
            with st.expander("Replace resume"):
                resume_uploader("settings")

        st.markdown("#### Today's usage")
        with st.container(border=True):
            for kind, label in [("fit_checks", "Role scores"), ("analyses", "Full analyses"),
                                ("discoveries", "Company searches")]:
                used = limits.daily_limit(user, kind) - limits.remaining(user, kind)
                st.progress(used / limits.daily_limit(user, kind),
                            text=f"{label}: {used} of {limits.daily_limit(user, kind)}")

        if AUTH_ENABLED:
            with st.expander("Delete my data"):
                st.caption("Permanently deletes your resume, searches, roles and analyses.")
                if st.checkbox("I understand this can't be undone") and st.button("Delete everything",
                                                                                   type="primary"):
                    database.delete_user(user["id"])
                    st.logout()


# --- Routing ------------------------------------------------------------------------------------
if not has_resume or not user["profile_json"] or not database.list_user_companies(user["id"]):
    onboarding()
else:
    st.navigation([
        st.Page(roles_page, title="Roles", icon=":material/work:", default=True),
        st.Page(match_page, title="Resume match", icon=":material/fact_check:", url_path="match"),
        st.Page(companies_page, title="Companies", icon=":material/apartment:", url_path="companies"),
        st.Page(saved_analyses_page, title="Analyses", icon=":material/description:", url_path="analyses"),
        st.Page(settings_page, title="Settings", icon=":material/settings:", url_path="settings"),
    ], position="top").run()
