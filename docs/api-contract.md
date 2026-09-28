# API contract

The contract between the React frontend (built in Lovable) and the Python API in this repo.
All requests and responses are JSON with **snake_case** field names, matching the Python models.
Every endpoint except `/api/auth/*` requires `Authorization: Bearer <token>`.

**Long-running actions are background jobs.** Endpoints marked *job* return `{ "job_id": "..." }` right away.
Poll `GET /api/jobs/{job_id}` every 2 seconds; it returns
`{ "status": "running" | "done" | "error", "log": string[], "result": <the documented return value> | null, "error": string | null }`.
`log` holds human-readable progress messages to show while the job runs.

## Types

```ts
type FitColor = "green" | "blue" | "orange" | "gray";   // strong | good | stretch | long shot
type Usage = { used: number; limit: number };

type Me = {
  name: string; email: string; is_owner: boolean;
  onboarding: { has_resume: boolean; has_search: boolean; has_companies: boolean };
  resume_kind: "pdf" | "text" | null;
  connections_count: number;
  last_scan: string | null;                 // human-readable summary of the last update
  usage: { fit_checks: Usage; analyses: Usage; discoveries: Usage; messages: Usage; coaching: Usage };
};

type SearchProfile = {
  include_titles: string[]; exclude_titles: string[]; locations: string[];
  interests: string; company_stage: string; min_score: number;
};

type RoleSummary = {
  id: number; title: string; company: string; company_id: number; logo_url: string | null;
  location: string; posted_at: string | null; url: string;
  fit_score: number; fit_color: FitColor; fit_label: string;   // e.g. 88, "green", "Strong fit"
  fit_reason: string;
  status: "new" | "saved" | "dismissed";
  has_plan: boolean; known_people: number;
};

type RolesResponse = {
  stats: { strong_count: number; saved_count: number; companies_watched: number; min_score: number };
  roles: RoleSummary[];                     // filtered by ?view=best|saved|all, best fit first
};

type StrongMatch = { skill: string; evidence: string };
type SkillGap = { skill: string; importance: "critical" | "important" | "nice-to-have"; why_it_matters: string };
type SkillToBuild = { skill: string; how: string };
type ResumeEdit = { original: string; suggested: string; why: string };
type AdjacentRoleType = { title: string; why: string };

type Analysis = {
  job_title: string; company: string; match_score: number; verdict: string;
  strong_matches: StrongMatch[]; skill_gaps: SkillGap[]; why_youre_a_fit: string[];
  what_to_emphasize: string[]; skills_to_build: SkillToBuild[];
  adjacent_roles: AdjacentRoleType[]; resume_edits: ResumeEdit[];
};

type PlanStep = {
  key: string; kind: "resume" | "skill" | "referral" | "story" | "apply";
  title: string; detail: string; done: boolean;
};

type Person = { index: number; name: string; position: string; url: string; why: string };

type Opening = { title: string; company: string; logo_url: string | null; location: string; url: string };

type RoleDetail = {
  role: RoleSummary;
  analysis: Analysis | null;                // null until the plan is built
  recommendation: { headline: string; detail: string; color: FitColor } | null;
  plan: PlanStep[];
  people: Person[];                         // connections at this company, most useful first
  has_connections: boolean;                 // has the user imported any connections at all
  adjacent: { title: string; why: string; in_search: boolean; openings: Opening[] }[];
};

type Company = {
  id: number;                               // the user's company entry
  name: string; logo_url: string | null;
  board_name: string | null; board_url: string | null;   // e.g. "Ashby", link to its job board
  why_it_fits: string; open_roles: number; known_people: number;
};

type CompaniesResponse = { suggested: Company[]; watching: Company[]; untrackable: Company[] };

type LearningStep = { action: string; time: string };
type SkillTheme = {
  skill: string; priority: "high" | "medium" | "low";
  roles: { title: string; company: string; role_id: number | null }[];
  why_it_matters: string; what_you_have: string; plan: LearningStep[]; proof_project: string;
};
type SkillsResponse = {
  analyses_count: number; min_analyses: number; new_since_report: number;
  report: { summary: string; themes: SkillTheme[]; roles_count: number; created_at: string } | null;
};

type SavedAnalysis = { id: number; title: string; company: string; match_score: number;
                       created_at: string; analysis: Analysis };
```

## Endpoints

| Method & path | Body | Returns |
|---|---|---|
| `GET /api/auth/login?redirect=<frontend url>` | | Redirects to Google; afterwards to `<redirect>#token=<token>` |
| `GET /api/me` | | `Me` |
| `DELETE /api/me` | | Deletes all of the user's data |
| `PUT /api/resume` | multipart form: `file` (PDF/txt) **or** `text` field | `Me` |
| `GET /api/search` · `PUT /api/search` | `SearchProfile` | `SearchProfile` |
| `GET /api/roles?view=best\|saved\|all&posted_within=<days>&sort=fit\|recent` | | `RolesResponse`. `posted_within` hides roles older than N days (and roles with no posting date); `sort=recent` puts the newest first |
| `POST /api/roles/refresh` | | *job* → `{ summary }`: checks tracked companies for new roles |
| `POST /api/roles/find` | | *job* → `{ summary }`: first run: discover companies, track them, scan (3–5 min) |
| `GET /api/roles/{id}` | | `RoleDetail` |
| `POST /api/roles/{id}/status` | `{ status }` | `RoleSummary` |
| `POST /api/roles/{id}/plan` | | *job* → `RoleDetail`: runs the full analysis (~40s) |
| `PUT /api/roles/{id}/plan/{step_key}` | `{ done }` | `PlanStep[]` |
| `POST /api/roles/{id}/draft` | `{ person_index }` | `{ message }` (~10s) |
| `POST /api/roles/{id}/add-title` | `{ title }` | `SearchProfile`: adds an adjacent role title to the search |
| `GET /api/companies` | | `CompaniesResponse` |
| `POST /api/companies/discover` | | *job* → `CompaniesResponse` (~2 min) |
| `POST /api/companies` | `{ name, careers_url? }` | `Company` or 404 if no job board found |
| `POST /api/companies/{id}/status` | `{ status: "tracking" \| "rejected" }` | `CompaniesResponse` |
| `DELETE /api/companies/{id}` | | `CompaniesResponse` |
| `POST /api/match` | `{ job_description }` | *job* → `Analysis` (~40s) |
| `GET /api/analyses` | | `SavedAnalysis[]` |
| `DELETE /api/analyses/{id}` | | `{}` |
| `GET /api/skills` | | `SkillsResponse` |
| `POST /api/skills` | | *job* → `SkillsResponse` (rebuilds the report, ~90s) |
| `PUT /api/connections` | multipart `file` (LinkedIn Connections.csv) | `{ count }` |
| `DELETE /api/connections` | | `{ count: 0 }` |
| `GET /api/jobs/{job_id}` | | job status, progress log and result (see above) |
| `GET /api/health` | | `{ ok: true }` |

Errors return `{ "detail": "<message for the user>" }` with 4xx/5xx status, e.g. 429 when a daily limit is reached.
