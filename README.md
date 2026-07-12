# Doctor Match

Cross-reference healthcare providers in the NPI Registry (NPPES) with investigators
listed on ClinicalTrials.gov, and surface a single merged profile for anyone who
shows up as a true match in both — matched by name and practice location.

No API key required — both the NPPES API and the ClinicalTrials.gov v2 API are public.

## Requirements

- Python 3.8+
- No third-party packages — everything uses the standard library (`urllib`, `http.server`, `difflib`, `argparse`).

## Setup

```bash
git clone https://github.com/adityabhowmick01-hub/doctor-match.git
cd doctor-match
```

That's it — there's nothing to install.

## Usage: CLI

```bash
python3 doctor_match.py --first-name Eric --last-name Topol --state CA
```

Options:

| Flag | Description |
|---|---|
| `--first-name` | Required. Provider's first name. |
| `--last-name` | Required. Provider's last name. |
| `--state` | Optional two-letter state code to narrow the NPI search (e.g. `CA`). |
| `--limit` | Max NPI providers to consider (default 20). |
| `--max-trials` | Max ClinicalTrials.gov studies to search (default 50). |
| `--min-confidence` | `low`, `medium`, or `high` — minimum match confidence to show (default `low`). |
| `--json` | Print raw JSON instead of formatted text. |

## Usage: web UI

```bash
python3 server.py
```

Then open `http://localhost:8768` in a browser. Enter a first/last name (and
optionally a state), and results render as cards with a confidence badge,
specialty, practice location, and a list of linked trials.

## How matching works

1. Query the NPI Registry for providers matching the name.
2. Query ClinicalTrials.gov for studies mentioning that name as a site investigator
   or trial official.
3. Compare first name and last name separately (not as one blended string) so a
   shared surname alone can't produce a false match.
4. Require the provider's practice state to match the investigator's site state.
   Per-site contacts are matched to their own site's city/state; trial-level
   "overall officials" (which aren't tied to a specific site) are only used when
   the name match is exact, since multi-site trials have no way to verify which
   site an overall official is actually affiliated with.
5. Confidence tiers: `high` (exact name + same city), `medium` (exact name + same
   state only), `low` (fuzzy name + same state).

Only true matches are returned — providers or trials with no match on the other
side are not shown.

## Known limitation

Common names (e.g. "Michael Chen") can still produce multiple `medium`-confidence
matches when several real people share the same name in the same state, since
name + location is the only signal available from these two public registries.
Treat `medium`/`low` confidence results as leads to verify, not certainties.
