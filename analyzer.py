"""Job-fit analysis: sends a resume + job description to Claude and gets back
a structured, validated assessment (not free-form text)."""

import base64
from typing import List, Literal

import anthropic
from pydantic import BaseModel, ConfigDict, Field

MODEL = "claude-opus-5"


# ---------------------------------------------------------------------------
# Output schema. Claude is constrained to return exactly this shape, so the
# result can be rendered in the UI and stored in the database.
# ---------------------------------------------------------------------------

class StrongMatch(BaseModel):
    skill: str = Field(description="A requirement from the job the candidate clearly meets")
    evidence: str = Field(description="Specific resume experience that proves it (company + what they did)")


class SkillGap(BaseModel):
    skill: str = Field(description="A requirement the resume shows little or no evidence of")
    importance: Literal["critical", "important", "nice-to-have"]
    why_it_matters: str = Field(description="Why this role needs it, in one sentence")


class SkillToBuild(BaseModel):
    skill: str
    how: str = Field(description="A concrete, short-term way to build or demonstrate this skill")


class ResumeEdit(BaseModel):
    original: str = Field(description="An existing line from the resume, quoted exactly")
    suggested: str = Field(description="The rewritten line, using only facts already in the resume")
    why: str = Field(description="What this change signals to this employer, in one sentence")


def _require_all_fields(schema: dict) -> None:
    schema["required"] = list(schema["properties"])


class JobFitAnalysis(BaseModel):
    # Every field is required when Claude generates an analysis; defaults below
    # only apply when loading older saved analyses.
    model_config = ConfigDict(json_schema_extra=_require_all_fields)

    job_title: str
    company: str = Field(description="Company name, or 'Unknown' if not stated")
    match_score: int = Field(description="Overall fit from 0 to 100")
    verdict: str = Field(description="Two-sentence bottom line: how competitive is this candidate and why")
    strong_matches: List[StrongMatch]
    skill_gaps: List[SkillGap]
    why_youre_a_fit: List[str] = Field(description="Arguments for the candidate, each tied to a specific role on the resume")
    what_to_emphasize: List[str] = Field(description="Ranked resume points to lead with in the application and interviews")
    skills_to_build: List[SkillToBuild] = Field(description="Ranked by impact on this candidate's chances")
    resume_edits: List[ResumeEdit] = Field(
        default_factory=list,
        description="3-5 rewrites of existing resume lines that would strengthen this application, most impactful first",
    )


# Shared with the quick fit check in scout.py so both use the same scale.
SCORING_GUIDE = """Scoring guide for match_score:
- 85-100: meets essentially all hard requirements; a strong interview candidate
- 70-84: meets most hard requirements; gaps are learnable or secondary
- 50-69: meaningful gaps in one or more hard requirements; a stretch application
- below 50: significant mismatch in seniority, domain, or core skills"""

SYSTEM_PROMPT = """You are an experienced tech recruiter and hiring manager who evaluates \
candidates for product roles. You compare a candidate's resume against a job description \
and give an honest, specific assessment of fit.

How to evaluate:
- Judge what the job actually requires, not keyword overlap. Infer skills from what the \
candidate did (e.g. "launched a pricing experiment to 10% of users" is evidence of A/B \
testing even if the phrase never appears). Equally, a listed buzzword with no supporting \
experience is weak evidence.
- Separate hard requirements from nice-to-haves using the job description's own language \
("required", "must", years of experience, vs. "bonus", "preferred").
- Every strength and every "why you're a fit" point must cite a specific role or project \
from the resume. Never invent experience the resume doesn't contain.
- For resume_edits, rewrite existing lines to foreground what this job values: reorder, \
use the employer's vocabulary for things the candidate actually did, and surface buried \
metrics. Only use facts already in the resume; never add skills, numbers or experience it \
doesn't contain. Don't try to paper over gaps with wording.
- Be candid about gaps. An inflated score is useless to someone deciding where to spend \
their application time.

""" + SCORING_GUIDE


class AnalysisError(Exception):
    """Raised when Claude doesn't return a usable analysis."""


def resume_block(resume_text: str | None, resume_pdf: bytes | None) -> dict:
    # PDFs go to Claude as-is, which reads them natively, so the app needs no
    # resume-parsing code of its own.
    if resume_pdf:
        return {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.standard_b64encode(resume_pdf).decode("utf-8"),
            },
            "title": "Candidate resume",
        }
    return {"type": "text", "text": f"<resume>\n{resume_text}\n</resume>"}


def analyze_fit(
    job_description: str,
    resume_text: str | None = None,
    resume_pdf: bytes | None = None,
    client: anthropic.Anthropic | None = None,
) -> JobFitAnalysis:
    """Compare a resume (plain text or PDF bytes) against a job description."""
    if not resume_text and not resume_pdf:
        raise ValueError("Provide the resume as text or as a PDF.")
    if not job_description.strip():
        raise ValueError("Job description is empty.")

    client = client or anthropic.Anthropic()

    response = client.messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    resume_block(resume_text, resume_pdf),
                    {
                        "type": "text",
                        "text": f"<job_description>\n{job_description}\n</job_description>\n\n"
                        "Evaluate how well this candidate fits this job.",
                    },
                ],
            }
        ],
        output_format=JobFitAnalysis,
    )

    if response.stop_reason == "refusal":
        raise AnalysisError("Claude declined to analyze this input.")
    if response.stop_reason == "max_tokens":
        raise AnalysisError("The analysis was cut off before it finished. Try a shorter job description.")
    if response.parsed_output is None:
        raise AnalysisError("Claude's response couldn't be parsed into the expected format.")

    return response.parsed_output
