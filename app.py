"""Streamlit UI for the AI Job Search Copilot.

Run with:  streamlit run app.py

With an [auth] section in .streamlit/secrets.toml, users sign in with Google
and each gets their own data. Without any secrets (plain local use), the app
runs as a single local user.
"""

import html
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

import database
import job_sources
import landing
import limits
import logos
import plans
import referrals
import scout
import styles
from analyzer import MODEL, analyze_fit
from discovery import discover_for_user
from search_profile import SearchProfile
from ui import fit_badge, fit_label, page_header, render_analysis, render_resume_edits, safe, show_errors

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
                company_id = database.upsert_company(name.strip(), *board, website=careers_url.strip())
                if database.add_user_company(user["id"], name.strip(), "", company_id, "tracking"):
                    st.success(f"Now tracking {name}.")
                else:
                    st.warning(f"{name} is already on your list.")
            else:
                st.error(f"Couldn't find a job board for {name}. We support companies hiring through "
                         "Greenhouse, Lever or Ashby. Try pasting a link to one of their job postings.")


def ensure_logos(company_ids: list[int]) -> None:
    """Look up logos for companies that haven't been checked yet (once per company, shared by all users)."""
    missing = database.companies_missing_logo([cid for cid in company_ids if cid])
    if not missing:
        return
    with st.spinner("Loading company logos…"), ThreadPoolExecutor(8) as pool:
        found = list(pool.map(lambda c: logos.find_logo(c["name"], c["website"] or ""), missing))
    for company, (domain, url) in zip(missing, found):
        database.set_company_logo(company["id"], domain, url)


def company_mark(name: str, logo_url: str | None, size: str = "") -> str:
    """HTML for a company's logo, or a colored initial if it has none."""
    if logo_url:
        return f'<img class="logo {size}" src="{html.escape(logo_url)}" alt="">'
    color = AVATAR_COLORS[sum(map(ord, name)) % len(AVATAR_COLORS)]
    return f'<div class="avatar {size}" style="background:{color}">{html.escape(name[:1].upper())}</div>'


@st.cache_data(ttl=60, show_spinner=False)
def _all_connections(user_id: int, version: str) -> list[dict]:
    return database.list_connections(user_id)


def connections_at(company: str) -> list[dict]:
    people = _all_connections(user["id"], st.session_state.get("connections_version", ""))
    return [c for c in people if referrals.same_company(c["company"], company)]


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
    with center, st.container(border=True, key="card-onboarding"):
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
        with st.container(border=True, key="card-suggested"):
            st.markdown(f"**We found {len(suggested)} companies that match you.** Scan them to see open roles.")
            if st.button("Find roles at these companies", type="primary"):
                find_roles()
                st.rerun()
        return

    ensure_logos([c["company_id"] for c in tracking])
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
            meta = [p["company"], p["location"] or "Location not listed"]
            if p["posted_at"]:
                meta.append(f"Posted {p['posted_at'][:10]}")
            st.html(f'<div class="role-head">{company_mark(p["company"], p["logo_url"], "small")}<div>'
                    f'<div class="role-title">{html.escape(p["title"])}</div>'
                    f'<div class="role-meta">{html.escape(" · ".join(meta))}</div></div></div>')
            with st.container(horizontal=True, gap="small"):
                fit_badge(p["fit_score"])
                if known := len(connections_at(p["company"])):
                    st.badge(f"You know {known} {'person' if known == 1 else 'people'} here",
                             icon=":material/group:", color="violet")
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

        label = "Open your plan to land it" if p["analysis_id"] else "Build your plan to land it"
        st.page_link(ROLE_PAGE, label=label, icon=":material/arrow_forward:", query_params={"id": p["id"]})


def role_page() -> None:
    role_id = st.query_params.get("id", "")
    p = database.get_user_posting(user["id"], int(role_id)) if role_id.isdigit() else None
    st.page_link(ROLES_PAGE, label="All roles", icon=":material/arrow_back:")
    if not p:
        st.warning("That role isn't in your list anymore.")
        return

    # Header
    with st.container(border=True, key="card-role-header"):
        info, actions = st.columns([5, 2], vertical_alignment="center")
        meta = [p["company"], p["location"] or "Location not listed"]
        if p["posted_at"]:
            meta.append(f"Posted {p['posted_at'][:10]}")
        info.html(f'<div class="role-head">{company_mark(p["company"], p["logo_url"])}<div>'
                  f'<div class="role-title big">{html.escape(p["title"])}</div>'
                  f'<div class="role-meta">{html.escape(" · ".join(meta))}</div></div></div>')
        with actions, st.container(horizontal=True, horizontal_alignment="right", gap="small"):
            st.link_button("View posting", p["url"], icon=":material/open_in_new:")
            saved = p["status"] == "saved"
            if st.button("Saved" if saved else "Save", icon=":material/bookmark" + ("" if saved else "_border") + ":",
                         type="primary" if saved else "secondary"):
                database.set_posting_status(user["id"], p["id"], "new" if saved else "saved")
                st.rerun()

    analysis = database.get_analysis(user["id"], p["analysis_id"]) if p["analysis_id"] else None
    if not analysis:
        with st.container(border=True, key="card-build-plan"):
            fit_badge(p["fit_score"])
            st.markdown(safe(p["fit_reason"]))
            st.markdown("**Get your plan to land this role:** what to change on your resume, which skills to build, "
                        "how to position yourself, and related roles where you may be even more competitive.")
            if st.button("Build my plan", type="primary", icon=":material/auto_awesome:"):
                with show_errors(), st.spinner("Analyzing the role against your resume… about 30 seconds"):
                    scout.analyze_posting(user, p)
                    st.rerun()
        return

    rec = plans.recommendation(analysis.match_score, p["company"])
    with st.container(border=True, key=f"role-{rec.color}-rec"):
        st.html('<div class="eyebrow">Our recommendation</div>')
        st.markdown(f"### {rec.headline}")
        fit_badge(analysis.match_score)
        st.markdown(f"{rec.detail}  \n:gray[{safe(analysis.verdict)}]")

    left, right = st.columns([3, 2], gap="large")
    with left:
        contacts = referrals.rank_contacts(connections_at(p["company"]), p["title"])
        has_connections = bool(_all_connections(user["id"], st.session_state.get("connections_version", "")))
        steps = plans.build_plan(analysis, p["company"], contacts, has_connections)
        done = database.get_plan_done(p)
        st.markdown("#### Your plan to land it")
        st.progress(len(done & {s.key for s in steps}) / len(steps),
                    text=f"{len(done & {s.key for s in steps})} of {len(steps)} done")
        for step in steps:
            with st.container(border=True, key=f"card-step-{step.key}"):
                checked = st.checkbox(f"**{safe(step.title)}**", value=step.key in done,
                                      key=f"plan-{p['id']}-{step.key}")
                st.caption(safe(step.detail))
                if checked != (step.key in done):
                    database.set_plan_done(user["id"], p["id"], done ^ {step.key})
                    st.rerun()
    with right:
        st.markdown("#### At a glance")
        with st.container(border=True, key="card-glance"):
            st.markdown("**Where you're strong**")
            for m in analysis.strong_matches[:4]:
                st.markdown(f":green[:material/check_circle:] {safe(m.skill)}")
            st.markdown("**Gaps**")
            for g in analysis.skill_gaps[:4]:
                label, color = {"critical": ("Critical", "red"), "important": ("Important", "orange"),
                                "nice-to-have": ("Nice to have", "gray")}[g.importance]
                st.markdown(f"{safe(g.skill)} :{color}-badge[{label}]")

        people_you_know(p, analysis, contacts, has_connections)

    adjacent_tab, resume_tab, full_tab = st.tabs(["Adjacent roles", "Resume suggestions", "Full analysis"])
    with adjacent_tab:
        adjacent_roles(analysis, p)
    with resume_tab:
        render_resume_edits(analysis)
    with full_tab:
        render_analysis(analysis, heading=False, resume_edits=False)


def people_you_know(p: dict, analysis, contacts: list, has_connections: bool) -> None:
    st.markdown(f"#### People you know at {p['company']}")
    with st.container(border=True, key="card-people"):
        if not has_connections:
            st.caption("Import your LinkedIn connections to see who can refer you.")
            st.page_link(SETTINGS_PAGE, label="Import connections", icon=":material/upload:")
            return
        if not contacts:
            st.caption(f"None of your connections work at {p['company']} yet.")
            return
        for i, c in enumerate(contacts):
            name = f"[{c.name}]({c.url})" if c.url else c.name
            st.markdown(f"**{name}**  \n:gray[{safe(c.position)}]")
            st.caption(c.why)
            draft_key = f"draft-{p['id']}-{i}"
            if st.button("Draft a message", key=f"btn-{draft_key}", icon=":material/edit:", type="tertiary"):
                with show_errors(), st.spinner("Drafting…"):
                    limits.require(user, "messages")
                    st.session_state[draft_key] = referrals.draft_message(
                        c, p["title"], p["company"], analysis, user["resume_text"], user["resume_pdf"])
                    limits.use(user, "messages")
            if draft_key in st.session_state:
                st.code(st.session_state[draft_key], language=None, wrap_lines=True)
                st.caption("Copy it, make it your own, and send it on LinkedIn.")
            if i < len(contacts) - 1:
                st.divider()


def adjacent_roles(analysis, p: dict) -> None:
    if not analysis.adjacent_roles:
        st.caption("Rebuild the plan to get adjacent role suggestions for this role.")
        return
    st.caption(f"Roles where your background may be as strong or stronger, at {p['company']} and the other "
               "companies you watch.")
    watched = [c["company_id"] for c in database.list_user_companies(user["id"], "tracking") if c["company_id"]]
    openings = database.open_postings_at(list({*watched, p["company_id"]}))
    for i, (title, why, matches) in enumerate(plans.find_adjacent_openings(analysis, p, openings)):
        with st.container(border=True, key=f"card-adjacent-{i}"):
            st.markdown(f"**{safe(title)}**")
            st.caption(safe(why))
            for m in matches:
                row, link = st.columns([6, 1], vertical_alignment="center")
                row.html(f'<div class="role-head">{company_mark(m["company"], m["logo_url"], "tiny")}<div>'
                         f'<div class="role-title small">{html.escape(m["title"])}</div>'
                         f'<div class="role-meta">{html.escape(m["company"] + " · " + (m["location"] or ""))}'
                         '</div></div></div>')
                link.link_button("View", m["url"], use_container_width=True)
            if not matches:
                st.caption("No open roles with this title at your companies right now.")
            if title.lower() not in {t.lower() for t in profile.include_titles}:
                if st.button(f"Add \"{title}\" to my search", key=f"add-title-{i}", icon=":material/add:",
                             type="tertiary"):
                    database.save_profile(user["id"], profile.model_copy(
                        update={"include_titles": [*profile.include_titles, title]}))
                    st.toast(f"Added. New {title} roles will show up after the next update.")


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

    ensure_logos([c["company_id"] for c in database.list_user_companies(user["id"])])
    role_counts = Counter(p["company_id"] for p in database.list_scored_postings(user["id"], 0))

    suggested = database.list_user_companies(user["id"], "suggested")
    if suggested:
        top, all_btn = st.columns([4, 1], vertical_alignment="bottom")
        top.markdown(f"#### Suggested for you ({len(suggested)})")
        if all_btn.button("Add all", type="primary", use_container_width=True):
            for c in suggested:
                database.set_user_company_status(user["id"], c["id"], "tracking")
            st.rerun()
        company_tiles(suggested, role_counts, suggested=True)
        st.space("medium")

    tracking = database.list_user_companies(user["id"], "tracking")
    st.markdown(f"#### Watching ({len(tracking)})")
    company_tiles(tracking, role_counts)

    st.space("medium")
    with st.expander("Add a company"):
        add_company_form()

    unverified = database.list_user_companies(user["id"], "unverified")
    if unverified:
        with st.expander(f"Can't be tracked automatically ({len(unverified)})"):
            st.caption("These companies don't publish a job feed we can read, often because they run their "
                       "own career sites. Check their careers pages directly.")
            for c in unverified:
                st.markdown(f"**{c['name']}**  \n{safe(c['why_it_fits'])}")


AVATAR_COLORS = ["#2451D6", "#5B3FD9", "#0F8A6A", "#D9480F", "#C2255C", "#1C7ED6", "#7048E8", "#2B8A3E"]
ATS_NAMES = {"greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby"}


def company_tiles(companies: list[dict], role_counts: Counter, suggested: bool = False, per_row: int = 3) -> None:
    for start in range(0, len(companies), per_row):
        for col, c in zip(st.columns(per_row, gap="medium"), companies[start:start + per_row]):
            with col:
                company_tile(c, role_counts.get(c["company_id"], 0), suggested)


def company_tile(c: dict, roles: int, suggested: bool) -> None:
    with st.container(border=True, key=f"tile-{c['id']}"):
        st.html(company_mark(c["name"], c["logo_url"]))
        st.markdown(f"**{c['name']}**")
        board = job_sources.board_page_url(c["ats"], c["ats_slug"])
        st.caption(f"[{ATS_NAMES[c['ats']]} job board]({board})")
        st.html(f'<div class="tile-why">{html.escape(c["why_it_fits"] or "Added by you")}</div>')
        with st.container(horizontal=True, gap="small"):
            if not suggested:
                label = f"{roles} role{'s' if roles != 1 else ''} for you"
                st.badge(label, color="blue" if roles else "gray", icon=":material/work:")
            if known := len(connections_at(c["name"])):
                st.badge(f"You know {known}", color="violet", icon=":material/group:")
        with st.container(horizontal=True, gap="small"):
            if suggested:
                if st.button("Add", key=f"track-{c['id']}", type="primary", icon=":material/add:"):
                    database.set_user_company_status(user["id"], c["id"], "tracking")
                    st.rerun()
                if st.button("Skip", key=f"skip-{c['id']}"):
                    database.set_user_company_status(user["id"], c["id"], "rejected")
                    st.rerun()
            elif st.button("Remove", key=f"stop-{c['id']}", type="tertiary", icon=":material/close:"):
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
        with st.container(border=True, key="card-analysis"):
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
        with st.container(border=True, key="card-account"):
            st.markdown(f"**{user['name'] or 'Signed in'}**  \n:gray[{user['email']}]")
            if AUTH_ENABLED:
                st.button("Sign out", on_click=st.logout, icon=":material/logout:")

        st.markdown("#### Resume")
        with st.container(border=True, key="card-resume"):
            st.markdown(f"Saved as {'PDF' if user['resume_pdf'] else 'text'}")
            with st.expander("Replace resume"):
                resume_uploader("settings")

        st.markdown("#### LinkedIn connections")
        with st.container(border=True, key="card-connections"):
            people = database.list_connections(user["id"])
            if people:
                st.markdown(f"**{len(people):,} connections** imported")
            st.caption("Used only to show who you know at each company. Emails aren't stored, and the app never "
                       "contacts anyone.")
            with st.expander("Import from LinkedIn" if not people else "Replace connections"):
                st.markdown("1. On LinkedIn, go to **Settings → Data privacy → Get a copy of your data**\n"
                            "2. Choose **Connections** and request the archive\n"
                            "3. When LinkedIn emails you, download it and upload **Connections.csv** here")
                upload = st.file_uploader("Connections.csv", type=["csv"], key="connections-file")
                if upload is not None and st.button("Import", type="primary"):
                    try:
                        imported = referrals.parse_linkedin_csv(upload.getvalue())
                    except ValueError as e:
                        st.error(str(e))
                    else:
                        database.replace_connections(user["id"], imported)
                        st.session_state["connections_version"] = str(len(imported)) + upload.name
                        st.rerun()
            if people and st.button("Delete connections", type="tertiary", icon=":material/delete:"):
                database.delete_connections(user["id"])
                st.session_state["connections_version"] = "deleted"
                st.rerun()

        st.markdown("#### Today's usage")
        with st.container(border=True, key="card-usage"):
            for kind, label in [("fit_checks", "Role scores"), ("analyses", "Full analyses"),
                                ("discoveries", "Company searches"), ("messages", "Drafted messages")]:
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
ROLES_PAGE = st.Page(roles_page, title="Roles", icon=":material/work:", default=True)
ROLE_PAGE = st.Page(role_page, title="Role", url_path="role", visibility="hidden")
SETTINGS_PAGE = st.Page(settings_page, title="Settings", icon=":material/settings:", url_path="settings")
if not has_resume or not user["profile_json"] or not database.list_user_companies(user["id"]):
    onboarding()
else:
    st.navigation([
        ROLES_PAGE,
        ROLE_PAGE,
        st.Page(match_page, title="Resume match", icon=":material/fact_check:", url_path="match"),
        st.Page(companies_page, title="Companies", icon=":material/apartment:", url_path="companies"),
        st.Page(saved_analyses_page, title="Analyses", icon=":material/description:", url_path="analyses"),
        SETTINGS_PAGE,
    ], position="top").run()
