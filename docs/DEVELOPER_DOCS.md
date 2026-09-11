# Router Task Manager — Developer Documentation

## Folder Structure

```
router-task-manager/
├── app.py                     # Flask application factory & entrypoint
├── config.py                  # Env-var-driven configuration
├── requirements.txt
├── .env.example
├── services/
│   └── router_service.py      # RouterService: all SSH + parsing logic
├── routes/
│   └── api.py                 # /api/* Flask Blueprint (thin, no SSH logic)
├── templates/
│   └── index.html             # Dashboard page (Jinja2 + Bootstrap 5)
├── static/
│   ├── css/style.css          # Dashboard styling
│   └── js/dashboard.js        # Polling, chart updates, DataTables wiring
└── docs/                      # This documentation set
```

## Class / Module Responsibilities

- **`Config` (`config.py`)** — single source of truth for all
  environment-derived settings. Nothing else reads `os.environ`
  directly.

- **`RouterService` (`services/router_service.py`)** — the only class
  that touches SSH. Public methods:
  - `check_health() -> dict`
  - `get_system_overview() -> dict`
  - `get_processes() -> dict`
  - `get_network_info() -> dict`
  - `close()`

  Internally it maintains one Paramiko `SSHClient`, guarded by a
  `threading.Lock`, and reconnects automatically when the transport is
  dead. All SSH commands are hard-coded (no dynamic command
  construction from external input).

- **`api_bp` (`routes/api.py`)** — a Flask Blueprint that simply calls
  the shared `RouterService` (via `current_app.router_service`) and
  returns its dict as JSON with the appropriate status code. Contains
  no business logic — keeping SSH/parsing concerns entirely inside
  `RouterService` makes it straightforward to unit-test the service in
  isolation from Flask.

## API Endpoints

| Method | Path             | Returns (on success)                                                        |
|--------|------------------|-------------------------------------------------------------------------------|
| GET    | `/`              | Rendered dashboard HTML                                                       |
| GET    | `/api/system`    | `{status, cpu_percent, cpu_history[], ram_percent, ram_total_mb, ram_used_mb, ram_free_mb, ram_history[], uptime_seconds, uptime_human, hostname, kernel_version, buildroot_version, error}` |
| GET    | `/api/processes` | `{status, processes: [{pid, user, name, cpu_percent, mem_percent, elapsed}], error}` |
| GET    | `/api/network`   | `{status, interfaces: [{name, ip_addresses[], mac_address}], default_gateway, error}` |
| GET    | `/api/health`    | `{status, error}`                                                              |

`status` is always `"online"` or `"offline"`. When `"offline"`,
`error` holds a human-readable message and other fields are `null` /
empty rather than omitted, so the frontend can rely on a stable shape.

## Data Flow

```
dashboard.js  --fetch()-->  routes/api.py  --calls-->  RouterService
                                                            │
                                                     Paramiko SSH
                                                            │
                                                    ConnectCo Router (Buildroot)
```

1. `dashboard.js` fires three parallel `fetch()` calls on page load and
   every `REFRESH_INTERVAL_MS`.
2. Each Flask route pulls the shared `RouterService` off
   `current_app` and calls the relevant `get_*` method.
3. `RouterService` ensures the SSH connection is alive, runs its fixed
   command set (with fallbacks), parses the output, and returns a
   plain `dict`.
4. The route wraps that `dict` in `jsonify(...)` with `200` or `503`.
5. `dashboard.js` updates the DOM, Chart.js instances, and the
   DataTables process table in place.

## How SSH Commands Are Executed

`RouterService._run(command)` is the single low-level execution point:
it calls `ensure_connected()`, then `exec_command()`, reads stdout, and
retries once (after forcing a reconnect) if the channel raised an
exception. `RouterService._run_first_success(commands)` layers fallback
behaviour on top — it tries each command in order and returns the first
non-empty result, used wherever router firmware might not support a
given tool/flag (e.g. `ps -eo ...` vs. plain `ps`, or `ip` vs.
`ifconfig`).

**Adding a new read-only metric:** add a new private `_get_x()` helper
to `RouterService` that calls `self._run(...)`/`self._run_first_success(...)`
and parses the result, expose it through a public `get_x()` method
following the existing `{status, ..., error}` shape, then add a route
in `routes/api.py` and a fetch call in `dashboard.js`.

**Do not** add any method that writes to the router (e.g. `iptables`,
`reboot`, config file writes) without first re-reading the project's
monitoring-only constraint — this is a deliberate design boundary, not
an oversight.

## How JSON Responses Are Generated

Every `get_*` method in `RouterService` returns a plain Python `dict`
with a fixed set of keys regardless of success or failure (fields are
`null` on failure rather than missing). `routes/api.py` calls
`jsonify()` on that dict directly — there is no separate serialization
layer.

## How the Frontend Updates Automatically

`static/js/dashboard.js`:
- `initCharts()` sets up two Chart.js line charts (CPU, RAM) on load.
- `initProcessTable()` sets up a DataTables instance (search, sort,
  and pagination come for free from DataTables).
- `refreshAll()` runs on page load and then every `REFRESH_INTERVAL_MS`
  (injected into the page from `Config.REFRESH_INTERVAL_MS` via Jinja2
  in `templates/index.html`), calling all three data endpoints in
  parallel with `Promise.all` and pushing the results into the DOM,
  charts, and table — never triggering a full page reload.
- Any fetch failure (network error or non-2xx response) sets the
  status badge to "Offline" rather than leaving stale data displayed
  silently.

## Testing Notes

The service layer was validated against a real local `sshd` (not just
mocked) during development, including a forced disconnect to exercise
the reconnect/offline path. If you change parsing logic, the fastest
way to verify it is to point `.env` at any reachable Linux box first
(`ROUTER_HOST=127.0.0.1` etc.) before testing against real router
hardware, since output-format assumptions are the most common source
of bugs here (see Technical Report §14 for the one real bug this
approach caught).
