# Field Coordinator Bot

Automate field research workflows and keep GitHub up to date with live field data.

This tool runs scripts (R, Python, Stata), reads their structured output, and syncs results into GitHub Issues and GitHub Projects. Workflows are declared in a simple YAML file and can be run manually, on a schedule, or triggered by a webhook.

Built for research teams that need an easy solution for live tracking of fieldwork/data collection progress.

---

## Requirements

- Python 3.9+
- A GitHub App with Issues and Projects read/write permissions

---

## Installation

```bash
git clone https://github.com/schneideraxel/field-coordinator-bot
cd field-coordinator-bot
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

---

## Configuration

Copy `.env.example` to `.env.local` and fill in your values:

```bash
cp .env.example .env.local
```

Minimum required:

```
GITHUB_APP_ID=your_app_id
GITHUB_INSTALLATION_ID=your_installation_id
GITHUB_PRIVATE_KEY=-----BEGIN RSA PRIVATE KEY-----\n...
WORKFLOW_FILE=workflows/workflows.yaml
```

Load before running:

```bash
set -a && source .env.local && set +a
```

---

## Defining workflows

Workflows are declared in `workflows/workflows.yaml`. That file contains a full reference section explaining all task types and options, and four annotated example workflows.

Quick example, run a check script and open one GitHub issue per flagged record:

```yaml
workflows:

  check_submissions:
    vars:
      repo: owner/myrepo
      project: Field Checks Board
    tasks:
      - action: run_script
        script: r/checks/check_submissions.R
        output_key: issues

      - action: foreach_rows
        sub_workflow: check_submissions_sub
        source: issues
        when: has_rows

  check_submissions_sub:
    tasks:
      - action: sync_issue
        repo: "{repo}"
        project: "{project}"
        title: "{case}"
        body: "{comment}"
        options: skip
      - action: sync_project
        repo: "{repo}"
        project: "{project}"
        options: skip
```

The script writes its output as JSON to the path in `$OUTPUT_FILE`. Example in R:

```r
rows <- list(
  list(case = "HH-001", comment = "Missing GPS coordinates"),
  list(case = "HH-042", comment = "Duplicate submission")
)
writeLines(jsonlite::toJSON(rows, auto_unbox = TRUE), Sys.getenv("OUTPUT_FILE"))
```

---

## CLI

| Command | Description |
|---|---|
| `python run.py workflow <name>` | Run a named workflow |
| `python run.py workflow <name> --dry-run` | Print planned tasks without executing |
| `python run.py list-workflows` | List all defined workflows |
| `python run.py list-tasks` | List all registered task types |
| `python run.py task <task> key=value ...` | Run a single task directly |
| `python run.py schedule --id <id> --workflow <name> --every <interval>` | Schedule an interval job |
| `python run.py schedule --id <id> --workflow <name> --cron "<expr>"` | Schedule a cron job |
| `python run.py list-jobs` | List scheduled jobs |
| `python run.py cancel-job --id <id>` | Cancel a scheduled job |
| `python run.py server` | Start the HTTP server |

### Examples

```bash
# Run a workflow by name
python run.py workflow check_submissions

# Pass a payload to override variables
python run.py workflow check_submissions '{"repo": "owner/myrepo"}'

# Dry-run to inspect the planned task list
python run.py workflow check_submissions --dry-run

# Run every 30 minutes (requires server to be running)
python run.py schedule --id check_30m --workflow check_submissions --every 30m

# Schedule with a cron expression (daily at 9am)
python run.py schedule --id check_daily --workflow check_submissions --cron "0 9 * * *"
```

---

## HTTP API

Start the server:

```bash
python run.py server
```

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/webhook` | Trigger a workflow from a webhook |
| `POST` | `/schedule/every` | Schedule an interval job |
| `POST` | `/schedule/cron` | Schedule a cron job |
| `GET` | `/jobs` | List scheduled jobs |
| `DELETE` | `/jobs/{job_id}` | Cancel a scheduled job |
| `GET` | `/recent` | Last 50 workflow run summaries |
| `GET` | `/healthz` | Health check |

---

## GitHub App setup

1. Go to `https://github.com/settings/apps` and create a new app
2. Grant **Issues: Read & Write** and **Projects: Read & Write** permissions
3. Install the app on your target repository or organization
4. Download the private key and set `GITHUB_PRIVATE_KEY` (inline PEM) in your `.env.local`

---

## License

MIT
