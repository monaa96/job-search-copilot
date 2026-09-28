"""Skill coaching: the gaps that keep coming up across a user's target roles.

Each full analysis lists skill gaps for one role, phrased for that role. This
module sends all of them to Claude at once to group differently worded gaps
into themes ("A/B testing", "experimentation" → one theme), rank them by how
often and how seriously they come up, and write a learning plan for each.
"""

from typing import List, Literal

import anthropic
from pydantic import BaseModel, Field

from analyzer import MODEL, JobFitAnalysis, resume_block

MIN_ANALYSES = 3


class LearningStep(BaseModel):
    action: str = Field(description="A concrete thing to do, e.g. 'Complete a SQL window functions tutorial'")
    time: str = Field(description="Rough time needed, e.g. '1 week, ~5 hours'")


class SkillTheme(BaseModel):
    skill: str = Field(description="Short name for the skill theme, e.g. 'Experimentation and A/B testing'")
    priority: Literal["high", "medium", "low"]
    role_indexes: List[int] = Field(description="Indexes of the roles (from the list given) that need this skill")
    why_it_matters: str = Field(description="One or two sentences on why the user's target roles need this")
    what_you_have: str = Field(description="What the resume already shows that the user can build on, or "
                                           "'Nothing yet' if nothing relevant")
    plan: List[LearningStep] = Field(description="3-5 steps, in order, from learning to demonstrating the skill")
    proof_project: str = Field(description="One small, concrete project that would show employers this skill")


class SkillReport(BaseModel):
    summary: str = Field(description="Two sentences: the pattern across the user's target roles and where to start")
    themes: List[SkillTheme] = Field(description="3-5 skill themes, highest priority first")


SYSTEM = """You are a career coach for someone in an active job search. You're given the skill gaps \
identified for each role they're targeting, plus their resume.

- Group gaps that describe the same underlying skill even when worded differently.
- Rank themes by how many target roles need them and how critical they are for those roles. A skill \
needed by one role is lower priority than one needed by most, unless it's critical to the user's top roles.
- Plans must be realistic for someone job searching: weeks, not years. Favor doing and demonstrating \
over studying. Only name well-known, widely available free resources, and don't include URLs.
- For technical skills (e.g. SQL, Python, APIs, ML concepts), be concrete about the level needed for \
these roles, not general mastery.
- Address the user as "you". Be direct and specific."""


def build_report(analyses: list[JobFitAnalysis], resume_text: str | None, resume_pdf: bytes | None,
                 client: anthropic.Anthropic | None = None) -> SkillReport:
    client = client or anthropic.Anthropic()
    roles = []
    for i, a in enumerate(analyses):
        gaps = "\n".join(f"  - {g.skill} ({g.importance}): {g.why_it_matters}" for g in a.skill_gaps)
        roles.append(f"Role {i}: {a.job_title} at {a.company} (fit {a.match_score})\n{gaps}")
    response = client.messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": [
            resume_block(resume_text, resume_pdf),
            {"type": "text", "text": "<target_roles>\n" + "\n\n".join(roles) + "\n</target_roles>\n\n"
                                     "Find the skill themes that matter most across these roles."},
        ]}],
        output_format=SkillReport,
    )
    if response.stop_reason in ("refusal", "max_tokens") or response.parsed_output is None:
        raise RuntimeError("Couldn't build your skills report. Try again.")
    return response.parsed_output
