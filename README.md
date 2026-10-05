# Canada Internship Fetcher

Overnight GitHub Actions pipeline that pulls public ATS job boards
(Greenhouse, Lever, Ashby), keeps only intern / co-op / student postings
located in Canada, and commits the results to `data/`.

## How it works

- `.github/workflows/nightly-fetch.yml` runs every night around 3 AM Toronto
  time (also runnable manually via "Run workflow"). GitHub may delay scheduled
  runs, so treat the time as approximate.
- `scripts/fetch_postings.py` (stdlib only, no pip install) fetches every
  board in `data/companies.json`, filters titles for intern/co-op/student,
  applies a hard Canada-only location gate (remote counts only if open to
  Canada), guesses the sector from the title, and writes:
  - `data/postings.json` — one row per live posting, in the same shape the
    Canada Internship Board's `saveverifieddiscoveries` action accepts
    (`company`, `title`, `location`, `posting_url`, `source`, plus `sector`,
    `posted_date`, `description`, `first_seen`, `last_seen`).
  - `data/meta.json` — run timestamp, counts.
- Listings not seen for 14 days are pruned (dead-link hygiene).
- The workflow commits the two JSON files back to the repo with the default
  `GITHUB_TOKEN` — no secrets to configure.

## Setup (2 minutes)

```bash
cd canada-internship-fetcher
gh auth login
gh repo create canada-internship-fetcher --public --source=. --push
```

Then open the repo on GitHub → Actions tab → enable workflows if prompted.
To test immediately: Actions → "Nightly internship fetch" → Run workflow.

## Adding a company

Append to `data/companies.json`:

```json
{"company": "Example Inc", "ats": "greenhouse", "board": "exampleinc",
 "note": "how the board id was verified"}
```

`ats` is one of `greenhouse`, `lever`, `ashby`. The `board` id comes from the
company's public board URL:
- Greenhouse: `boards-api.greenhouse.io/v1/boards/<board>/jobs`
- Lever: `api.lever.co/v0/postings/<board>`
- Ashby: `api.ashbyhq.com/posting-api/job-board/<board>`

Only add boards you verified return live JSON (the script logs failures).

## Feeding the board

`data/postings.json` rows already match the board's discovery schema. When
you're ready, the board can ingest them (e.g. a small sync that fetches the
raw JSON and calls `saveverifieddiscoveries`), replacing the paused in-agent
nightly refresh.
