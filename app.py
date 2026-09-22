"""Streamlit UI for the AI Job Search Copilot.

Run with:  streamlit run app.py
"""

import anthropic
import streamlit as st
from dotenv import load_dotenv

import database
from analyzer import MODEL, AnalysisError, JobFitAnalysis, analyze_fit

load_dotenv()
database.init_db()

st.set_page_config(page_title="Job Search Copilot", page_icon="🧭", layout="wide")

IMPORTANCE_ICON = {"critical": "🔴", "important": "🟠", "nice-to-have": "⚪"}


def render_analysis(a: JobFitAnalysis) -> None:
    st.subheader(f"{a.job_title} — {a.company}")

    score_col, verdict_col = st.columns([1, 4])
    score_col.metric("Overall match", f"{a.match_score}%")
    verdict_col.info(a.verdict)

    left, right = st.columns(2)
    with left:
        st.markdown("#### ✅ Strong matches")
        for m in a.strong_matches:
            st.markdown(f"**{m.skill}** — {m.evidence}")
    with right:
        st.markdown("#### △ Skill gaps")
        for g in a.skill_gaps:
            st.markdown(f"{IMPORTANCE_ICON[g.importance]} **{g.skill}** ({g.importance}) — {g.why_it_matters}")

    st.markdown("#### Why you're a fit")
    for point in a.why_youre_a_fit:
        st.markdown(f"- {point}")

    left, right = st.columns(2)
    with left:
        st.markdown("#### What to emphasize")
        for i, point in enumerate(a.what_to_emphasize, 1):
            st.markdown(f"{i}. {point}")
    with right:
        st.markdown("#### Skills to build")
        for i, s in enumerate(a.skills_to_build, 1):
            st.markdown(f"{i}. **{s.skill}** — {s.how}")


# --- Sidebar: resume -------------------------------------------------------
with st.sidebar:
    st.header("Your resume")
    uploaded = st.file_uploader("Upload a PDF or text file", type=["pdf", "txt", "md"])
    pasted = st.text_area("…or paste it here", height=300)

    resume_text, resume_pdf = None, None
    if uploaded is not None:
        if uploaded.type == "application/pdf" or uploaded.name.lower().endswith(".pdf"):
            resume_pdf = uploaded.getvalue()
        else:
            resume_text = uploaded.getvalue().decode("utf-8", errors="ignore")
    elif pasted.strip():
        resume_text = pasted

    if resume_pdf or resume_text:
        st.success("Resume loaded")

# --- Main area ---------------------------------------------------------------
st.title("🧭 AI Job Search Copilot")
st.caption("Paste a job description to see how well you fit, what you're missing, and what to do about it.")

analyze_tab, history_tab = st.tabs(["Analyze a job", "Saved analyses"])

with analyze_tab:
    job_description = st.text_area("Job description", height=300, placeholder="Paste the full job posting…")

    if st.button("Analyze fit", type="primary", disabled=not job_description.strip()):
        if not (resume_pdf or resume_text):
            st.error("Add your resume in the sidebar first.")
        else:
            try:
                with st.spinner("Comparing your experience to the role… (this can take a minute)"):
                    result = analyze_fit(job_description, resume_text=resume_text, resume_pdf=resume_pdf)
                database.save_analysis(job_description, result, MODEL)
                st.session_state["latest"] = result
            except anthropic.AuthenticationError:
                st.error("Your Anthropic API key is missing or invalid. Check the ANTHROPIC_API_KEY in your .env file.")
            except anthropic.RateLimitError:
                st.error("Rate limited by the API. Wait a moment and try again.")
            except anthropic.APIConnectionError:
                st.error("Couldn't reach the Anthropic API. Check your internet connection.")
            except anthropic.APIStatusError as e:
                st.error(f"API error ({e.status_code}): {e.message}")
            except AnalysisError as e:
                st.error(str(e))

    if "latest" in st.session_state:
        st.divider()
        render_analysis(st.session_state["latest"])

with history_tab:
    saved = database.list_analyses()
    if not saved:
        st.write("No analyses yet. Run one in the first tab and it'll be saved here.")
    for row in saved:
        label = f"{row['result'].match_score}% · {row['title']} — {row['company']} · {row['created_at'][:10]}"
        with st.expander(label):
            render_analysis(row["result"])
            if st.button("Delete", key=f"delete-{row['id']}"):
                database.delete_analysis(row["id"])
                st.rerun()
