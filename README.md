# Job Search Copilot

Finding a job is a job in itself. Job Search Copilot finds roles that fit you, shows exactly what stands between you and each one, and gives you a concrete plan to land it.

- Live app: [job-search-copilot.lovable.app](https://job-search-copilot.lovable.app)
- This repository: the Python backend (AI analysis, job scanning, data and API)
- Frontend: a React app built with Lovable, which calls the API described in [docs/api-contract.md](docs/api-contract.md)

## The problem

Job seekers repeat the same manual work every day. They check a dozen career pages, skim postings, read each job description against their own experience, guess whether they are competitive, and try to figure out what is missing. Job boards help with finding roles, and resume tools help with matching keywords, but neither answers the questions that matter most:

- Which of these roles am I actually competitive for?
- What exactly is missing between my background and this role?
- What should I do about it, and who could help me get in?

## Who it's for

People in an active job search, especially career switchers and people moving up a level, who need to spend their limited time on the right roles. It was built first for product managers, which is my own search.

## What it does

The product covers three stages: find, diagnose and act.

**Find**
- You describe what you want (titles, locations, industries, company stage) and upload your resume.
- An AI agent researches companies that fit your interests and background, then checks which ones publish a job feed the app can read.
- Every morning, the app scans those companies' job boards for new roles that match your titles and locations.
- You can filter roles by posting date and sort by best fit or most recent.

**Diagnose**
- Every new role gets a fit score from 0 to 100 against your resume, with one sentence explaining the deciding factor.
- For any role, a full analysis shows where you are strong (with evidence from your resume), what is missing (ranked critical, important or nice to have) and what to emphasize.
- Across every role you have analyzed, the app finds the skill gaps that keep coming up, so you can see patterns instead of one job at a time.

**Act**
- Each role gets a plan to land it: a recommendation (apply now, apply with a tailored resume, apply with a referral, or look at adjacent roles first) and a checklist you can track.
- Resume suggestions rewrite your existing bullets in the language of the role, without adding anything your resume does not support.
- If you import your LinkedIn connections, each role shows who you know at the company, ranked by who can help most, and drafts a referral message for you to send.
- Adjacent roles suggest related titles where you may be even more competitive, matched to real open postings.
- A skills plan gives you a learning plan and a small proof project for each recurring gap.

## Product hypothesis

If a job seeker gets a short, ranked list of new roles each morning, with an honest assessment and a concrete plan for each one, they will apply to fewer roles, apply to the right ones, and get more interviews because they arrive with a tailored resume and a referral.

## How it works

1. Company discovery: Claude researches companies that match the user's interests, using web search, and returns each one with a reason it fits this person.
2. Verification: the app checks each company for a public job feed (Greenhouse, Lever or Ashby). Companies without one are listed separately so the user can check them manually.
3. Daily scan: a scheduled job fetches every open role at the companies each user watches, applies that user's title and location filters, and stores the matches.
4. Quick fit check: each new role is scored against the user's resume with a short AI call. Unscored roles still appear right away, labeled as not scored yet.
5. Full analysis: when the user opens a role, a deeper AI analysis produces the strengths, gaps, resume edits and adjacent roles, and the app turns that into a recommendation and checklist.
6. Referrals and coaching: connections are matched to companies in code, and the AI drafts outreach messages and cross-role learning plans on request.

## Key product and technical decisions

**Use an agent only where the path is unpredictable.** Finding companies is open-ended, so an agent decides what to search for and when it has enough. Scoring hundreds of roles a day needs predictable cost and behavior, so that part is a fixed pipeline with AI judgment only inside specific steps.

**AI proposes, software verifies, the user decides.** The discovery agent can suggest companies that do not fit or get details wrong, so every suggestion is checked against a real job feed before it is used, and users can remove or add companies at any time.

**Official job feeds instead of scraping.** Greenhouse, Lever and Ashby publish public job feeds that companies expect to be read. Scraping LinkedIn or Indeed would break their terms and break often. The tradeoff is coverage: companies that run their own career sites, such as Apple and Amazon, cannot be tracked automatically yet.

**Trust the source for dates.** The app uses each company's own publish date. Early on, it used the "last updated" date for some boards, which made months-old roles look new because companies edit postings often. That was a real user complaint, and fixing it made the date filter trustworthy.

**A cost funnel.** Free keyword filters run first, a cheap quick check scores only new roles, and the expensive full analysis runs only when someone opens a role. The newest roles are scored first, so each day's budget goes to fresh postings.

**Structured outputs instead of free text.** Every AI step returns data in a fixed schema, so results can be ranked, stored, compared across roles and turned into checklists. The schema is effectively the product spec for what a useful fit assessment contains.

**Honest by design.** Every strength must cite a specific role on the resume, and resume suggestions may only reword what is already there. The quick check and the full analysis share one scoring rubric, so a 75 means the same thing everywhere.

**Referrals without scraping or spam.** Connections come from LinkedIn's official data export. The app stores names, companies, titles and profile links, discards email addresses, never contacts anyone, and only drafts messages for the user to review and send.

**Cost controls for a public app.** Every user has daily limits on scoring, analyses, company searches, drafted messages and skills reports, with higher limits for the owner. The cost of each new user is bounded and predictable.

## Architecture

| Layer | Technology | Notes |
|---|---|---|
| Frontend | React, TypeScript, Tailwind (built with Lovable) | Hosted by Lovable |
| API | Python, FastAPI | Hosted on Render |
| AI | Claude API | Structured outputs, web search |
| Database | Postgres (Neon) | SQLite for local development |
| Sign-in | Google | Signed session tokens issued by the API |
| Daily scan | GitHub Actions | Runs every morning for all users |

Long actions, such as finding roles or building a skills report, run as background jobs. The frontend polls for progress and shows each step as it happens, which avoids request timeouts and keeps the user informed.

### Files in this repository

| File | What it does |
|---|---|
| `api.py` | The REST API used by the frontend, including sign-in and background jobs |
| `analyzer.py` | Full fit analysis: the prompt, the output schema and the Claude call |
| `scout.py` | The daily scan: fetch, filter, quick fit check and optional full analyses |
| `discovery.py` | Company discovery with web search, then extraction and verification |
| `job_sources.py` | Finds a company's job board and reads its postings |
| `plans.py` | Turns an analysis into a recommendation, a checklist and adjacent openings |
| `referrals.py` | Reads LinkedIn's connections file, matches people to companies, drafts messages |
| `coaching.py` | Groups skill gaps across roles into themes with learning plans |
| `database.py` | Users, companies, postings, analyses, connections and usage |
| `limits.py` | Per-user daily usage limits |
| `logos.py` | Company logos |
| `docs/api-contract.md` | The contract between the frontend and the API |
| `.github/workflows/daily-scan.yml` | The scheduled daily scan |
| `render.yaml` | Hosting configuration for the API |
| `app.py`, `ui.py`, `styles.py`, `landing.py` | The original Streamlit prototype, still runnable locally |

## Running it locally

You need Python 3.10 or newer and an [Anthropic API key](https://console.anthropic.com).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Add your API key to `.env`, then start the API with local sign-in enabled:

```bash
DEV_LOGIN=1 uvicorn api:app --reload --port 8000
```

Locally the API uses a SQLite file in `data/`. The original Streamlit prototype also still runs with `streamlit run app.py`.

## Deploying

- API: deploy to Render with `render.yaml`, and set `ANTHROPIC_API_KEY`, `DATABASE_URL`, `OWNER_EMAILS`, `SECRET_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `API_BASE_URL` and `FRONTEND_ORIGINS`.
- Google sign-in: add `<API_BASE_URL>/api/auth/callback` as an authorized redirect URI.
- Daily scan: add `ANTHROPIC_API_KEY`, `DATABASE_URL` and `OWNER_EMAILS` as GitHub repository secrets.
- Frontend: point its API base URL at the deployed API.

## Privacy

Resumes, searches, connections and results are private to each user, and users can delete all of their data from the app. The full policy is in [PRIVACY.md](PRIVACY.md) and on the live site.

## What I learned building it

- Real use beats planning. Several of the most important changes came from using the app for my own search: people wanted to see roles, not a list of companies to approve; long-open roles looked new because of a date bug; and adding a company did nothing until the next day.
- Data quality is a product problem. A wrong posting date made a correct feature feel broken. Checking the source data directly was faster than guessing.
- The hard part of AI features is making the output trustworthy. Fixed schemas, a shared scoring rubric, required evidence and rules against invented experience mattered more than the prompt wording.
- Coverage is a real tradeoff. Official job feeds are reliable and legitimate but miss large companies with their own career sites. That gap is now the top item on the roadmap.

## Roadmap

- Coverage for large companies that run their own career sites, starting with a direct link to their search results and then a Workday connector or a licensed job data source
- A "first seen" date for roles whose company does not publish one, and a signal for roles that have been open a long time
- Adding many companies at once by pasting a list
- An application tracker with applied, interviewing and offer stages, contacts and follow-ups, building on the plan checklist
- Learning from your choices: using saves, dismissals and outcomes to improve suggestions and scoring
- A morning email with your new matches

## How it was built

I designed the product, made the scoping and tradeoff decisions, and tested it in my own job search. The code was written with AI coding tools: Claude Code for the backend and the AI features, and Lovable for the frontend.
