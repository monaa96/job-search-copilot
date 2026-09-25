# AI Job Search Copilot

> Which jobs am I actually a fit for, why, what am I missing, and what should I do about it?

An AI job scout. Sign in, upload your resume, say what you're looking for, and it:

1. **Finds companies** that match your interests and background, using an AI agent that researches the web
2. **Scans their job boards every morning** for new roles that match your target titles and locations
3. **Scores every new job against your resume** and ranks your daily list by fit
4. **Explains the fit in depth**: evidence-backed strengths, prioritized skill gaps, what to emphasize, and specific rewrites of your resume bullets for that role

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
   Track every verified company           ← user can add, remove or re-run discovery anytime
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
   Roles: ranked by fit; save, dismiss, or get a full analysis with resume suggestions
```

**Stack:** Python · Claude API (structured outputs, web search) · Streamlit (UI and Google sign-in) · Postgres in the cloud / SQLite locally, via SQLAlchemy · GitHub Actions for the daily scan

| File | Role |
|---|---|
| `app.py` | Streamlit interface: sign-in, first-run setup, and the main tabs |
| `landing.py` | The page visitors see before signing in |
| `analyzer.py` | Full fit analysis and resume suggestions: prompt, output schema, and the Claude call |
| `discovery.py` | Company discovery: web research, then structured extraction and verification |
| `job_sources.py` | Finds a company's job board and fetches its postings |
| `scout.py` | The daily scan pipeline, for one user or all users |
| `database.py` | Users, companies, postings, analyses and usage; SQLite or Postgres |
| `limits.py` | Per-user daily usage limits |
| `search_profile.py` | A user's search preferences |
| `.github/workflows/daily-scan.yml` | Runs the scan for every user each morning |
| `schedule_daily_scan.sh` | Alternative: schedules the scan on your own Mac |
| `sample_data/` | Fictional resume, job description and analysis |

## Key product and technical decisions

**Agent where the path is unpredictable, workflow where cost and reliability matter.** Finding companies is open-ended, so an agent decides what to search and when it has enough. Scanning hundreds of jobs a day needs predictable cost and behavior, so it's a fixed pipeline with AI judgment only inside specific steps.

**AI proposes, software verifies, the user stays in control.** The discovery agent can suggest companies that don't fit or get details wrong, so each suggestion is checked against a real job feed before it's used. Early versions asked users to approve every company before scanning, but users wanted to see roles, not companies, so setup now goes straight from "what are you looking for" to a ranked list of roles, and companies can be pruned or added afterwards.

**A cost funnel.** Free filters run first, a cheap quick check scores only *new* jobs, and the expensive full analysis runs only on the top few. Each scan has hard caps, and jobs over the cap wait for the next scan rather than being dropped.

**Official job feeds, not scraping.** Greenhouse, Lever and Ashby publish public job feeds. Scraping LinkedIn or Indeed would violate their terms, break often, and get blocked. The tradeoff: companies with their own hiring systems (often the largest ones) can't be tracked automatically, so they're shown separately for manual follow-up.

**Structured outputs instead of free text.** Every AI step returns data in a fixed schema (`match_score`, `strong_matches`, `skill_gaps`, …), so results can be ranked, stored, and later aggregated across jobs. The schema is the product spec for "what a useful fit assessment contains."

**Evidence required, calibrated scores.** Every strength must cite a specific role on the resume, and invented experience is forbidden. Both the quick check and the full analysis share one written scoring rubric, so a 75 means the same thing everywhere.

**Shared where it's public, private where it's personal.** Companies and job postings are shared across users, so a board is fetched once no matter how many people track it. Resumes, searches, scores and analyses are per user, and users can delete all their data from the app. PDFs go straight to the model, so there's no resume-parsing code.

**Cost controls for a public app.** Every user has daily limits on fit checks, full analyses and company searches (owners get higher limits), on top of the account-level spending cap. The cost of adding a user is bounded and predictable.

**Resume suggestions that can't lie.** Each analysis rewrites 3–5 existing resume lines in the employer's vocabulary. The prompt forbids adding skills, numbers or experience the resume doesn't contain.

**Fail-safe hosting.** If the hosted app's sign-in isn't configured, it only shows the public landing page, so visitors can never end up sharing an account.

## Running it locally

Requires Python 3.10+ and an [Anthropic API key](https://console.anthropic.com). Locally, the app runs as a single user with a SQLite database, with no sign-in needed.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then paste your API key into .env
streamlit run app.py
```

Then follow the in-app setup: resume → what you're looking for → companies → **Scan now**.

To scan automatically every morning on your own Mac:

```bash
./schedule_daily_scan.sh          # daily at 8:00; or e.g. ./schedule_daily_scan.sh 7 30
./schedule_daily_scan.sh remove   # turn it off
```

## Deploying the public version

1. **Database:** create a free Postgres database (e.g. [Neon](https://neon.tech)) and copy its connection string.
2. **Google sign-in:** in Google Cloud Console, create an OAuth client (type "Web application") with the redirect URI `https://<your-app>.streamlit.app/oauth2callback`.
3. **Streamlit Community Cloud:** deploy `app.py` from this repo, with these Secrets:
   ```toml
   ANTHROPIC_API_KEY = "..."
   DATABASE_URL = "postgresql://..."
   OWNER_EMAILS = "you@example.com"

   [auth]
   redirect_uri = "https://<your-app>.streamlit.app/oauth2callback"
   cookie_secret = "<a long random string>"
   client_id = "..."
   client_secret = "..."
   server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
   ```
4. **Daily scan:** add `ANTHROPIC_API_KEY`, `DATABASE_URL` and `OWNER_EMAILS` as GitHub repository secrets. The workflow in `.github/workflows/daily-scan.yml` then runs every morning, and can be triggered manually from the Actions tab.

**Cost:** a full analysis costs a few cents. Company discovery costs roughly $0.50–1 per run because of web search. After the first scan, daily scans only process new postings.

## Roadmap

1. ✅ **Job-fit analyzer**: resume + job description → structured analysis
2. ✅ **Company discovery and daily job scan**
3. ✅ **Public multi-user version**: Google sign-in, per-user data and limits, cloud daily scan, resume suggestions
4. **Learns from your choices**: use save/dismiss history to improve which companies are suggested and how jobs are scored
5. **Takes actions**: for saved jobs, draft a tailored resume version and an outreach message, with user approval before anything is used
6. **Pursues a goal**: "find me 10 strong-fit roles this month"; the agent keeps researching and scanning until it gets there, and reports what it tried
7. **Application tracker**: status per job (applied → interviewing → offer), contacts, follow-ups
8. **Email digest**: "5 new matches for you" each morning
9. **Cross-job insights**: "Across the jobs I've saved, what skills am I consistently missing?", aggregating `skill_gaps` to set skill-building priorities

## Tradeoffs and what I learned

<!-- TODO: fill in after using it on your real search: where scores were right or wrong, what you changed, and why -->
