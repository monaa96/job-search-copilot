"""The page visitors see before signing in."""

from pathlib import Path

import streamlit as st

from analyzer import JobFitAnalysis
from ui import render_analysis

SAMPLES = Path(__file__).parent / "sample_data"
REPO_URL = "https://github.com/monaa96/job-search-copilot"


def render(sign_in_available: bool = True) -> None:
    st.title("🧭 AI Job Search Copilot")
    st.markdown("#### Your AI job scout: new roles that fit you, every morning.")

    steps = st.columns(3)
    steps[0].markdown("**1. Tell it about you**  \nUpload your resume and say what roles and companies interest you.")
    steps[1].markdown("**2. It finds and scans**  \nAI researches matching companies, then checks their job boards daily.")
    steps[2].markdown("**3. You get a ranked list**  \nEach new role is scored against your resume, with specific resume edits.")

    if sign_in_available:
        st.button("Sign in with Google to get started", type="primary", on_click=st.login)
    else:
        st.info("Sign-ups open soon. Meanwhile, see an example analysis below.")
    st.caption(f"Free to try, with daily usage limits. Your resume is only used to score jobs for you, "
               f"and you can delete your data anytime. [Privacy policy](?page=privacy) · [How it works ↗]({REPO_URL})")

    st.divider()
    st.subheader("Example: a full fit analysis")
    st.caption("A real output for a fictional candidate and job.")
    render_analysis(JobFitAnalysis.model_validate_json((SAMPLES / "sample_analysis.json").read_text()))
