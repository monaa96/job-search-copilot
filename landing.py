"""The page visitors see before signing in."""

from pathlib import Path

import streamlit as st

from analyzer import JobFitAnalysis
from ui import render_analysis

SAMPLES = Path(__file__).parent / "sample_data"
REPO_URL = "https://github.com/monaa96/job-search-copilot"

FEATURES = [
    ("blue", ":material/travel_explore:", "Finds companies for you",
     "Researches companies that match your interests and background, then watches their job boards."),
    ("violet", ":material/insights:", "Ranks every new role",
     "Each morning, new openings are scored against your resume, so the best fits rise to the top."),
    ("teal", ":material/edit_note:", "Tailors your resume",
     "For any role, see where you're strong, what's missing, and exactly how to reword your resume."),
]


def render(sign_in_available: bool = True) -> None:
    st.space("medium")
    _, center, _ = st.columns([1, 6, 1])
    with center:
        with st.container(key="hero"):
            st.markdown("# Find the roles you're actually a fit for")
            st.markdown("Job Search Copilot scans the companies that match you every day, ranks new openings "
                        "against your resume, and shows you how to stand out for each one.")
            if sign_in_available:
                st.button("Sign in with Google", icon=":material/login:", on_click=st.login)
                st.caption(f"Free to use, with daily limits. You can delete your data anytime. "
                           f"[Privacy](?page=privacy) · [How it's built]({REPO_URL})")
            else:
                st.markdown("**Sign-ups are opening soon.**")

        st.space("large")
        for col, (color, icon, title, text) in zip(st.columns(3, gap="medium"), FEATURES):
            with col, st.container(border=True, height="stretch", key=f"feature-{color}"):
                st.markdown(f"#### {icon}")
                st.markdown(f"**{title}**")
                st.caption(text)

        st.space("large")
        st.markdown("### See an example")
        st.caption("A real analysis for a fictional candidate and role.")
        with st.container(border=True):
            render_analysis(JobFitAnalysis.model_validate_json((SAMPLES / "sample_analysis.json").read_text()))
