"""Company discovery: turns the user's interests into a list of companies to track.

Two steps:
1. Research: Claude uses web search to find companies that fit the profile.
2. Extract: a second call turns that research into a validated list.
Each company is then checked in job_sources for a public job feed before the
user is asked to approve it.
"""

from typing import List

import anthropic
from pydantic import BaseModel, Field

from analyzer import MODEL, resume_block
from search_profile import SearchProfile

MAX_CONTINUATIONS = 5


class CompanySuggestion(BaseModel):
    name: str
    why_it_fits: str = Field(description="One sentence tying the company to the candidate's interests and background")
    careers_url: str = Field(description="URL of the company's careers or job board page, or empty string if unknown")


class CompanySuggestions(BaseModel):
    companies: List[CompanySuggestion]


RESEARCH_PROMPT = """You are helping a job seeker build a list of companies to watch for openings.

<search_profile>
Interests and industries: {interests}
Company stage / size: {stage}
Locations: {locations}
Target roles: {titles}
</search_profile>

Companies already on their list (don't repeat these): {existing}

Use web search to find about {count} companies that fit this profile and are plausibly \
hiring for the target roles. Use the attached resume to favor companies where this \
candidate's background would be a credible fit.

For each company, find its careers page. Companies whose jobs are hosted on Greenhouse \
(boards.greenhouse.io / job-boards.greenhouse.io), Lever (jobs.lever.co), or Ashby \
(jobs.ashbyhq.com) are especially useful, because the app can track those automatically; \
when you find such a job board link, give that link as the careers URL.

Finish with a list: company name, one sentence on why it fits this candidate, and the careers URL."""


def suggest_companies(
    profile: SearchProfile,
    existing_names: list[str],
    resume_text: str | None = None,
    resume_pdf: bytes | None = None,
    count: int = 15,
    client: anthropic.Anthropic | None = None,
) -> list[CompanySuggestion]:
    client = client or anthropic.Anthropic()

    content = []
    if resume_text or resume_pdf:
        content.append(resume_block(resume_text, resume_pdf))
    content.append({
        "type": "text",
        "text": RESEARCH_PROMPT.format(
            interests=profile.interests or "(not specified)",
            stage=profile.company_stage or "(any)",
            locations=", ".join(profile.locations) or "(any)",
            titles=", ".join(profile.include_titles) or "(any)",
            existing=", ".join(existing_names) or "(none)",
            count=count,
        ),
    })
    messages = [{"role": "user", "content": content}]
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 10}]

    # Step 1: research. Web search runs server-side; if the server pauses a
    # long turn, re-send the conversation so it resumes where it left off.
    for _ in range(MAX_CONTINUATIONS):
        with client.messages.stream(
            model=MODEL, max_tokens=32000, messages=messages, tools=tools
        ) as stream:
            response = stream.get_final_message()
        if response.stop_reason != "pause_turn":
            break
        messages = [messages[0], {"role": "assistant", "content": response.content}]

    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined the company research request.")
    research = "\n".join(b.text for b in response.content if b.type == "text").strip()
    if not research:
        raise RuntimeError("Company research came back empty. Try again.")

    # Step 2: turn the research notes into structured data.
    extracted = client.messages.parse(
        model=MODEL,
        max_tokens=8000,
        output_config={"effort": "low"},
        messages=[{
            "role": "user",
            "content": f"Extract every company recommended in these research notes.\n\n<notes>\n{research}\n</notes>",
        }],
        output_format=CompanySuggestions,
    )
    if extracted.parsed_output is None:
        raise RuntimeError("Couldn't read the company list from Claude's research.")

    existing = {n.lower() for n in existing_names}
    return [c for c in extracted.parsed_output.companies if c.name.lower() not in existing]
