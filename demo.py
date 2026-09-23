"""Public demo of the job-fit analyzer, for the hosted deployment.

Differences from the full app:
- Nothing is saved: the resume and results live only in the visitor's session.
- A sample analysis is shown for free; live analysis requires a passcode, and
  each session is capped, so strangers can't run up API costs.
- Company discovery and the daily scan are local-only features.
"""

import hmac
import os
from pathlib import Path

import streamlit as st

from analyzer import JobFitAnalysis, analyze_fit
from ui import render_analysis, show_errors

SAMPLES = Path(__file__).parent / "sample_data"
MAX_ANALYSES_PER_SESSION = 5
REPO_URL = "https://github.com/monaa96/job-search-copilot"


def _passcode_ok(entered: str) -> bool:
    expected = os.getenv("DEMO_PASSCODE", "")
    return bool(expected) and hmac.compare_digest(entered.encode(), expected.encode())


def render() -> None:
    st.title("🧭 AI Job Search Copilot")
    st.markdown(
        "Compares a resume against a job description and returns an honest, evidence-backed fit "
        "assessment: match score, strengths, skill gaps, and what to do about them."
    )
    st.info(
        f"**Public demo.** Nothing you enter is saved. The full version also finds companies that "
        f"match your interests and scans their job boards every morning. "
        f"[See how it works on GitHub ↗]({REPO_URL})"
    )

    sample_tab, try_tab = st.tabs(["👀 Sample analysis", "✏️ Try it yourself"])

    with sample_tab:
        st.caption("A real output for a fictional candidate ([resume](" + REPO_URL + "/blob/main/sample_data/"
                   "sample_resume.txt)) and job ([posting](" + REPO_URL + "/blob/main/sample_data/"
                   "sample_job_description.txt)).")
        render_analysis(JobFitAnalysis.model_validate_json((SAMPLES / "sample_analysis.json").read_text()))

    with try_tab:
        if st.button("Fill in the sample resume and job"):
            st.session_state["demo_resume"] = (SAMPLES / "sample_resume.txt").read_text()
            st.session_state["demo_jd"] = (SAMPLES / "sample_job_description.txt").read_text()

        left, right = st.columns(2)
        uploaded = left.file_uploader("Resume (PDF)", type=["pdf"])
        resume_text = left.text_area("…or paste resume text", height=250, key="demo_resume")
        job_description = right.text_area("Job description", height=330, key="demo_jd")

        used = st.session_state.get("demo_runs", 0)
        passcode = st.text_input("Passcode", type="password",
                                 help="Live analysis uses a paid API, so it's passcode-protected. "
                                      "Ask the author for access, or explore the sample analysis.")
        ready = (uploaded or resume_text.strip()) and job_description.strip() and passcode
        if st.button("Analyze fit", type="primary", disabled=not ready):
            if not _passcode_ok(passcode):
                st.error("That passcode isn't right.")
            elif used >= MAX_ANALYSES_PER_SESSION:
                st.error(f"This demo is limited to {MAX_ANALYSES_PER_SESSION} analyses per visit.")
            else:
                st.session_state["demo_runs"] = used + 1
                with show_errors(), st.spinner("Comparing experience to the role… (about 30 seconds)"):
                    st.session_state["demo_result"] = analyze_fit(
                        job_description,
                        resume_text=None if uploaded else resume_text,
                        resume_pdf=uploaded.getvalue() if uploaded else None,
                    )

        if "demo_result" in st.session_state:
            st.divider()
            render_analysis(st.session_state["demo_result"])
