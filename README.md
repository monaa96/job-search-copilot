# AI Job Search Copilot

> Which jobs am I actually a fit for, why, what am I missing, and what should I do about it?

An AI tool that compares a resume against a job description and returns a structured assessment: a match score, strengths backed by evidence, prioritized skill gaps, and concrete next steps.

<!-- TODO (milestone 2): add screenshots of the analyze screen and saved analyses -->

## The problem

Job seekers repeat the same manual analysis for every posting: read the JD, map it against their experience, guess whether they're competitive, and figure out what's missing. It's slow, inconsistent, and biased toward keyword matching, when what matters is whether your *experience* meets what the role *requires*.

## Product hypothesis

If a candidate can get an honest, evidence-backed fit assessment in under a minute, they'll spend application time on roles where they're competitive and tailor each application to the strengths that matter most for that role.

## MVP scope (V1)

**In scope:** resume (PDF, text, or pasted) + job description → structured fit analysis → saved to a local database and viewable later.

**Deliberately out of scope for now:** job scraping, live job feeds, LinkedIn/email integration, networking/contact tracking, authentication, RAG, custom resume parsing. The goal of V1 is to prove the core loop is useful before adding anything else.

## Architecture

```text
Resume + Job description
          ↓
   Python (analyzer.py)
          ↓
   Claude API  ── semantic comparison, not keyword overlap
          ↓
   Structured JSON (validated by a Pydantic schema)
          ↓
   SQLite (database.py)
          ↓
   Streamlit UI (app.py)
```

| File | Role |
|---|---|
| `analyzer.py` | Prompt, output schema, and the Claude API call |
| `database.py` | SQLite tables for `jobs` and `analyses` |
| `app.py` | Streamlit interface |
| `sample_data/` | Fictional resume and JD for trying the app |

## Key technical decisions

- **Structured outputs instead of free text.** The model is constrained to a schema (`match_score`, `strong_matches`, `skill_gaps`, …), so results can be rendered consistently, stored, and later aggregated across many jobs. The schema is the product spec for "what a useful fit assessment contains."
- **Evidence required.** The prompt requires every strength to cite a specific role on the resume and forbids invented experience. That keeps the output checkable.
- **Calibrated scoring.** The prompt defines what each score band means, so a 75 carries the same meaning across jobs.
- **PDFs go straight to the model.** Claude reads PDFs natively, so there's no fragile resume-parsing code.
- **`jobs` and `analyses` are separate tables.** A job can be re-analyzed against an updated resume, and the planned application tracker attaches to `jobs`.
- **Streamlit** for a working UI in ~100 lines, since the value is in the analysis, not the frontend.

## Running it locally

Requires Python 3.10+ and an [Anthropic API key](https://console.anthropic.com).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then paste your API key into .env
streamlit run app.py
```

Try it with the files in `sample_data/`.

## Roadmap

1. ✅ **Job-fit analyzer**: resume + JD → structured analysis
2. **Polished repo**: screenshots, a sample output, and lessons learned
3. **Application tracker**: status per job (saved → applied → interviewing → offer), contacts, follow-ups, dashboard
4. **Cross-job insights**: "Across the 25 PM jobs I've saved, what skills am I consistently missing?", which aggregates `skill_gaps` across the database to set skill-building priorities

## Tradeoffs and what I learned

<!-- TODO: fill in after using it on real job postings: where the analysis was right or wrong, prompt changes you made, and why -->
