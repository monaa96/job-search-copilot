"""Display helpers shared across pages."""

from contextlib import contextmanager

import anthropic
import streamlit as st

from analyzer import AnalysisError, JobFitAnalysis

IMPORTANCE_BADGE = {"critical": ("Critical", "red"), "important": ("Important", "orange"),
                    "nice-to-have": ("Nice to have", "gray")}


@contextmanager
def show_errors():
    """Turn API and app errors into readable messages instead of stack traces."""
    try:
        yield
    except anthropic.AuthenticationError:
        st.error("The AI service rejected the API key. Check the ANTHROPIC_API_KEY setting.")
    except anthropic.RateLimitError:
        st.error("The AI service is busy right now. Wait a moment and try again.")
    except anthropic.APIConnectionError:
        st.error("Couldn't reach the AI service. Check your internet connection.")
    except anthropic.APIStatusError as e:
        st.error(f"The AI service returned an error ({e.status_code}): {e.message}")
    except (AnalysisError, RuntimeError) as e:
        st.error(str(e))


def safe(text: str) -> str:
    """Escape AI-written text for st.markdown, which treats $...$ as math."""
    return (text or "").replace("$", "\\$")


def fit_label(score: int) -> tuple[str, str]:
    """(label, badge color) for a fit score, matching the scoring rubric."""
    if score >= 85:
        return "Strong fit", "green"
    if score >= 70:
        return "Good fit", "blue"
    if score >= 50:
        return "Stretch", "orange"
    return "Long shot", "gray"


def fit_badge(score: int) -> None:
    label, color = fit_label(score)
    st.badge(f"{score} · {label}", color=color)


def page_header(title: str, subtitle: str = "", eyebrow: str = "") -> None:
    if eyebrow:
        st.html(f'<div class="eyebrow">{eyebrow}</div>')
    st.markdown(f"## {title}")
    if subtitle:
        st.caption(subtitle)


def render_analysis(a: JobFitAnalysis, heading: bool = True) -> None:
    if heading:
        st.markdown(f"### {safe(a.job_title)}")
        st.caption(a.company)
    fit_badge(a.match_score)
    st.markdown(safe(a.verdict))

    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("##### Where you're strong")
        for m in a.strong_matches:
            st.markdown(f"**{safe(m.skill)}**  \n{safe(m.evidence)}")
    with right:
        st.markdown("##### Gaps")
        for g in a.skill_gaps:
            label, color = IMPORTANCE_BADGE[g.importance]
            st.markdown(f"**{safe(g.skill)}** :{color}-badge[{label}]  \n{safe(g.why_it_matters)}")

    st.markdown("##### Why you're a fit")
    for point in a.why_youre_a_fit:
        st.markdown(f"- {safe(point)}")

    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("##### What to emphasize")
        for i, point in enumerate(a.what_to_emphasize, 1):
            st.markdown(f"{i}. {safe(point)}")
    with right:
        st.markdown("##### Skills to build")
        for i, s in enumerate(a.skills_to_build, 1):
            st.markdown(f"{i}. **{safe(s.skill)}**: {safe(s.how)}")

    if a.resume_edits:
        st.markdown("##### Resume suggestions for this role")
        for i, edit in enumerate(a.resume_edits):
            with st.container(border=True, key=f"card-edit-{id(a)}-{i}"):
                st.caption("Current")
                st.markdown(safe(edit.original))
                st.caption("Suggested")
                st.markdown(f"**{safe(edit.suggested)}**")
                st.caption(safe(edit.why))
