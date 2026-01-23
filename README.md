# Field Coordinator Bot

Field Coordinator Bot is an automation engine for monitoring field data collection workflows and synchronizing results into GitHub issues and GitHub Projects.

It pulls survey data from collection tools, runs scripted checks and progress analyses, and publishes structured updates to GitHub to support fieldwork tracking and coordination.

---

## What this program does

- Runs data workflows defined in a CSV file  
- Executes scripts (R, Python, shell, etc.) as workflow steps  
- Iterates over script outputs and applies follow-up tasks  
- Syncs results into GitHub issues and GitHub Projects  
- Supports manual runs, scheduled runs, and webhook-triggered runs  
- Prevents missed runs and overlapping executions  

---

## Typical use cases

- Monitor survey submission progress by site, team, or enumerator  
- Run automated consistency or quality checks on incoming field data  
- Generate structured summaries and dashboards  
- Create or update GitHub issues for fieldwork follow-up  
- Keep GitHub Projects in sync with live field progress  

---

## Architecture overview

- **Workflow definitions** live in a CSV file  
- **Scripts** (e.g. R or Python) generate structured JSON outputs  
- **Python tasks** consume those outputs and sync to GitHub  
- A **workflow engine** builds and executes ordered task pipelines  
- A **scheduler** runs workflows periodically  
- A **FastAPI server** exposes HTTP endpoints and webhooks  
- A **Typer CLI** supports manual execution and job control  

---

## Requirements

- Python 3.9+  
- R (optional, if running R scripts)  
- GitHub App credentials  
- Credentials for survey or data collection APIs  

---

## Installation

```bash
git clone <repo-url>
cd field-coordinator-bot

python -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

---

## Environment configuration

Create a `.env.local` file:

```bash
export R_WORKSPACE_ROOT=/path/to/your/scripts
export WORKFLOW_CSV=workflows/workflows.csv
export GITHUB_APP_ID=xxxx
export GITHUB_INSTALLATION_ID=xxxx
export GITHUB_PRIVATE_KEY_PATH=secrets/github-app.pem
```

Load it before running anything:

```bash
set -a
source .env.local
set +a
source venv/bin/activate
```

---

## Workflow definition (CSV)

Workflows are defined row-by-row in a CSV file.

Example:

```csv
macro,workflow,task_order,sub_workflow,action,script,source,repo,project,title,body,options
monitor_progress,monitor_progress,1,,run_script,scripts/progress_report.R,,,,,,
monitor_progress,monitor_progress,2,progress_rows,foreach_rows,,,,,,,
,progress_rows,1,,sync_issue,,,{repo},{project},{case},{summary},skip
,progress_rows,2,,sync_project,,,{repo},{project},,,update
```

---

## Running workflows manually

```bash
python run.py workflow monitor_progress
```

---

## Scheduling workflows

Run every 30 minutes:

```bash
python run.py schedule   --workflow monitor_progress   --id monitor_progress_30m   --every 30m
```

List scheduled jobs:

```bash
python run.py list-jobs
```

Cancel a job:

```bash
python run.py cancel-job --id monitor_progress_30m
```

---

## Running the API server

```bash
uvicorn app.interfaces.http.server:app --reload
```

Endpoints:

- `POST /webhook` — trigger workflows from webhooks  
- `POST /schedule/every` — schedule interval jobs  
- `POST /schedule/cron` — schedule cron jobs  
- `GET /jobs` — list scheduled jobs  
- `DELETE /jobs/{job_id}` — cancel a job  
- `GET /recent` — recent workflow runs  
- `GET /healthz` — health check  

---

## Scheduler behavior

- Jobs run inside the FastAPI process  
- Late runs execute once instead of being skipped  
- Multiple missed runs are coalesced into one  
- The same job can never overlap with itself  
- Jobs are stored in memory and cleared on restart  

---

## Key design principles

- Declarative workflows (CSV-driven)  
- Script-agnostic execution (R, Python, shell, etc.)  
- Deterministic task ordering  
- Idempotent GitHub synchronization  
- Non-overlapping scheduled runs  
- Minimal operational complexity  

---

## Notes

- Scheduled jobs are not persisted across restarts  
- Cancelling a job prevents future runs but does not stop a run in progress  
- Script outputs must be JSON-serializable for downstream tasks  

---

## License

MIT License

Copyright (c) 2026

Permission is hereby granted, free of charge, to any person obtaining a copy  
of this software and associated documentation files (the "Software"), to deal  
in the Software without restriction, including without limitation the rights  
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell  
copies of the Software, and to permit persons to whom the Software is  
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all  
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR  
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,  
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE  
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER  
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,  
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE  
SOFTWARE.
