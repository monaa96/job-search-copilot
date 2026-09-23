# AI Job Search Copilot

> Which jobs am I actually a fit for, why, what am I missing, and what should I do about it?

An AI job-search assistant. Tell it what you're interested in, and it:

1. **Finds companies** that match your interests and background, using an AI agent that researches the web
2. **Scans their job boards every morning** for new roles that match your target titles and locations
3. **Scores every new job against your resume** and ranks your daily list by fit
4. **Explains the fit in depth**: evidence-backed strengths, prioritized skill gaps, what to emphasize, and what to learn

<!-- TODO: add screenshots of Today's jobs, Companies, and a full analysis (use sample data) -->

## The problem

Job seekers repeat the same manual work every day: check a dozen career pages, skim postings, read each job description against their experience, guess whether they're competitive, and figure out what's missing. It's slow and inconsistent, and job boards match on keywords, when what matters is whether your *experience* meets what the role *requires*.

## Product hypothesis

If a candidate gets a short, ranked list of new roles each morning, each with an honest, evidence-backed fit assessment, they'll spend their time on roles where they're competitive and tailor each application to what that role cares about.

## How it works

```text
 "My search": interests, stage, locations, titles
                   │
                   ▼
 ┌──────────────────────────────────┐
 │ Company discovery (agentic)      │  Claude + web search decides what to research
 │                                  │  and returns companies with a "why it fits you"
 └──────────────────────────────────┘
                   │
                   ▼
   Verify each has a public job feed      ← software check (Greenhouse / Lever / Ashby APIs)
                   │
                   ▼
   User approves which to track           ← human judgment
                   │
                   ▼
 ┌──────────────────────────────────┐
 │ Daily scan (workflow, 8am)       │
 │  fetch all open jobs      free   │
 │  keyword filter           free   │
 │  quick AI fit check       cheap  │  new jobs only, capped per scan
 │  full analysis            $$     │  top matches only
 └──────────────────────────────────┘
                   │
                   ▼
   Today's jobs: ranked by fit; save, dismiss, or analyze
```

**Stack:** Python · Claude API (structured outputs, web search) · SQLite · Streamlit · macOS launchd for scheduling

| File | Role |
|---|---|
| `app.py` | Streamlit interface |
| `analyzer.py` | Full fit analysis: prompt, output schema, and the Claude call |
| `discovery.py` | Company discovery: web research, then structured extraction |
| `job_sources.py` | Finds a company's job board and fetches its postings |
| `scout.py` | The daily scan pipeline (also runs from the command line) |
| `database.py` | SQLite: companies, postings, analyses, settings |
| `search_profile.py` | Search preferences and the saved resume |
| `schedule_daily_scan.sh` | Schedules the daily scan on macOS |
| `sample_data/` | Fictional resume and job description for trying the app |

## Key product and technical decisions

**Agent where the path is unpredictable, workflow where cost and reliability matter.** Finding companies is open-ended, so an agent decides what to search and when it has enough. Scanning hundreds of jobs a day needs predictable cost and behavior, so it's a fixed pipeline with AI judgment only inside specific steps.

**AI proposes, software verifies, the human decides.** The discovery agent can suggest companies that don't fit or get details wrong. Each suggestion is checked against a real job feed before it's shown, and nothing is tracked until the user approves it.

**A cost funnel.** Free filters run first, a cheap quick check scores only *new* jobs, and the expensive full analysis runs only on the top few. Each scan has hard caps, and jobs over the cap wait for the next scan rather than being dropped.

**Official job feeds, not scraping.** Greenhouse, Lever and Ashby publish public job feeds. Scraping LinkedIn or Indeed would violate their terms, break often, and get blocked. The tradeoff: companies with their own hiring systems (often the largest ones) can't be tracked automatically, so they're shown separately for manual follow-up.

**Structured outputs instead of free text.** Every AI step returns data in a fixed schema (`match_score`, `strong_matches`, `skill_gaps`, …), so results can be ranked, stored, and later aggregated across jobs. The schema is the product spec for "what a useful fit assessment contains."

**Evidence required, calibrated scores.** Every strength must cite a specific role on the resume, and invented experience is forbidden. Both the quick check and the full analysis share one written scoring rubric, so a 75 means the same thing everywhere.

**Private by default.** The resume and database stay on the user's machine and are excluded from git. PDFs go straight to the model, so there's no resume-parsing code.

## Running it locally

Requires macOS or Linux, Python 3.10+, and an [Anthropic API key](https://console.anthropic.com).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then paste your API key into .env
streamlit run app.py
```

Then follow the in-app steps: save your resume → fill in **My search** → find and approve companies → **Scan now**.

To scan automatically every morning (macOS):

```bash
./schedule_daily_scan.sh          # daily at 8:00; or e.g. ./schedule_daily_scan.sh 7 30
./schedule_daily_scan.sh remove   # turn it off
```

**Cost:** a full analysis costs a few cents. Company discovery costs roughly $0.50–1 per run because of web search. After the first scan, daily scans only process new postings.

## Roadmap

1. ✅ **Job-fit analyzer**: resume + job description → structured analysis
2. ✅ **Company discovery and daily job scan**
3. **Learns from your choices**: use save/dismiss history to improve which companies are suggested and how jobs are scored
4. **Takes actions**: for saved jobs, draft a tailored resume version and an outreach message, with user approval before anything is used
5. **Pursues a goal**: "find me 10 strong-fit roles this month"; the agent keeps researching and scanning until it gets there, and reports what it tried
6. **Application tracker**: status per job (applied → interviewing → offer), contacts, follow-ups
7. **Cross-job insights**: "Across the jobs I've saved, what skills am I consistently missing?", aggregating `skill_gaps` to set skill-building priorities

## Tradeoffs and what I learned

<!-- TODO: fill in after using it on your real search: where scores were right or wrong, what you changed, and why -->
