# Router Task Manager

A Windows-Task-Manager-style live monitoring dashboard for a ConnectCo
router running Buildroot Linux. Flask + Paramiko backend over SSH;
Bootstrap 5 + Chart.js + DataTables frontend, auto-refreshing every 5
seconds. **Monitoring only** — it never modifies router configuration.

## Quick Start

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then edit .env with your router's SSH details
python3 app.py
```

Open `http://localhost:5000`.

## Documentation

- [`docs/USER_MANUAL.md`](docs/USER_MANUAL.md) — installation, configuration, running, troubleshooting
- [`docs/TECHNICAL_REPORT.md`](docs/TECHNICAL_REPORT.md) — architecture, design decisions, testing approach
- [`docs/DEVELOPER_DOCS.md`](docs/DEVELOPER_DOCS.md) — folder structure, class responsibilities, API reference, data flow

## Architecture

```
Browser  --HTTP/JSON-->  Flask Backend  --SSH-->  ConnectCo Router (Buildroot)
```

The browser never talks to the router directly and never sees SSH
credentials.
