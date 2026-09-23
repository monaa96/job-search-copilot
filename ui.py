"""Display helpers shared by the full app and the public demo."""

from contextlib import contextmanager

import anthropic
import streamlit as st

from analyzer import AnalysisError, JobFitAnalysis

IMPORTANCE_ICON = {"critical": "🔴", "important": "🟠", "nice-to-have": "⚪"}


@contextmanager
def show_errors():
    """Turn API and app errors into readable messages instead of stack traces."""
    try:
        yield
    except anthropic.AuthenticationError:
        st.error("Your Anthropic API key is missing or invalid. Check the ANTHROPIC_API_KEY in your .env file.")
    except anthropic.RateLimitError:
        st.error("Rate limited by the API. Wait a moment and try again.")
    except anthropic.APIConnectionError:
        st.error("Couldn't reach the Anthropic API. Check your internet connection.")
    except anthropic.APIStatusError as e:
        st.error(f"API error ({e.status_code}): {e.message}")
    except (AnalysisError, RuntimeError) as e:
        st.error(str(e))


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

    if a.resume_edits:
        st.markdown("#### ✍️ Resume suggestions for this role")
        for edit in a.resume_edits:
            with st.container(border=True):
                st.markdown(f"~~{edit.original}~~")
                st.markdown(f"**→ {edit.suggested}**")
                st.caption(edit.why)
