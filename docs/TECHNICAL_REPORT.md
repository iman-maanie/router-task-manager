# Router Task Manager — Technical Report

## 1. Introduction

Router Task Manager is a web-based monitoring dashboard for a ConnectCo
router running Buildroot Linux. It gives engineers a live, browser-based
view of router health — CPU, memory, uptime, running processes, and
network configuration — refreshed automatically every five seconds,
without needing to open an SSH terminal by hand.

## 2. Project Objectives

- Provide a Windows-Task-Manager-style view of a remote embedded Linux router.
- Connect to the router exclusively over SSH, never exposing credentials
  or a direct network path to the browser.
- Refresh data automatically without page reloads.
- Remain strictly **read-only** — the application has no code path capable
  of changing router configuration.
- Degrade gracefully (display "Offline") if the router is unreachable,
  rather than crashing.

## 3. System Architecture

```
Browser  --HTTP/JSON-->  Flask Backend  --SSH (Paramiko)-->  ConnectCo Router
```

The browser only ever calls the Flask REST API (`/api/system`,
`/api/processes`, `/api/network`, `/api/health`). Flask is the sole
component that opens an SSH session, using credentials loaded from a
local `.env` file that is never served to the client. There is no
route, parameter, or code path that lets the browser send an arbitrary
command to the router.

## 4. Technologies Used

**Backend:** Python 3, Flask, Paramiko (SSH client), Flask-CORS,
python-dotenv.

**Frontend:** HTML5, CSS3, vanilla JavaScript (`fetch`), Bootstrap 5,
Chart.js for the CPU/memory history graphs, and DataTables (jQuery) for
the sortable/searchable/paginated process table.

## 5. SSH Communication

`services/router_service.py` defines `RouterService`, which:

- Opens a single reusable Paramiko `SSHClient` connection (key-based or
  password auth, configured via `.env`).
- Automatically reconnects if the transport has dropped, retrying each
  command once after a fresh connection attempt.
- Runs a small, fixed set of **read-only** diagnostic commands
  (`cat /proc/stat`, `free -m`, `ps`, `ip addr show`, `uname -r`, etc.),
  with fallback commands for systems where a given tool or flag isn't
  available (e.g. BusyBox `ps` vs. full `procps` `ps`).
- Never accepts a command string from the browser — the command list is
  hard-coded in the service layer.

## 6. Application Workflow

1. The browser loads the dashboard (`GET /`).
2. JavaScript calls `/api/system`, `/api/processes`, and `/api/network`
   in parallel immediately, then again every `REFRESH_INTERVAL_MS`
   (default 5000ms) via `setInterval`.
3. Each request triggers `RouterService` to run its diagnostic commands
   over the existing (or freshly re-established) SSH session.
4. Raw command output is parsed into structured JSON and returned with
   an appropriate HTTP status (`200` when online, `503` when the router
   is unreachable).
5. The frontend updates cards, charts, and the process table in place —
   no page reload.

## 7. Backend Design

- `app.py` — Flask application factory; wires up CORS, the API
  blueprint, and a single shared `RouterService` instance attached to
  the app object.
- `config.py` — loads all configuration (router host/credentials, Flask
  host/port, refresh interval) from environment variables.
- `services/router_service.py` — all SSH logic and output parsing.
- `routes/api.py` — thin Flask Blueprint exposing the REST endpoints;
  contains no SSH or parsing logic itself.

## 8. Frontend Design

- `templates/index.html` — Bootstrap 5 layout: summary cards, two
  Chart.js line charts (CPU history, memory history), a DataTables
  process table, and network/system information panels.
- `static/css/style.css` — a professional, engineering-oriented colour
  palette (navy header, neutral card surfaces, blue/green/amber/red
  accent colours for status and CPU load).
- `static/js/dashboard.js` — polls the API on an interval, updates DOM
  elements and charts, and feeds the process table via DataTables.

## 9. API Design

| Endpoint          | Method | Description                                   |
|--------------------|--------|-----------------------------------------------|
| `/api/system`      | GET    | CPU %, RAM %, uptime, hostname, kernel, Buildroot version |
| `/api/processes`   | GET    | Full process list (PID, user, name, CPU%, mem%, elapsed) |
| `/api/network`     | GET    | Interfaces, IP addresses, MAC addresses, default gateway |
| `/api/health`      | GET    | Lightweight online/offline check                        |

All endpoints return JSON and use HTTP `200` when the router responded
successfully, or `503` with a structured `error` field when it did not.

## 10. Process Monitoring

CPU usage is computed from two `/proc/stat` samples taken a fraction of
a second apart (rather than parsing `top`, whose column layout varies
significantly between BusyBox and full `procps` builds). Process listing
tries several `ps` command variants in order, since BusyBox `ps` on
Buildroot commonly supports fewer columns than a full desktop Linux
`ps`; the parser recognises three common output shapes (see
`_parse_ps_line` in `router_service.py`) and fills unavailable fields
with `null` rather than guessing.

## 11. Charts and Visualisations

Chart.js renders two rolling line charts (CPU % and RAM % over time,
capped at the most recent 30 samples) fed by a server-side history
buffer (`collections.deque`) maintained per metric in `RouterService`.

## 12. Security Considerations

- SSH credentials live only in `.env` on the server; they are never
  sent to, or readable by, the browser.
- The command set run on the router is fixed and read-only — there is
  no user-controllable input that reaches the SSH channel.
- `AutoAddPolicy` is used for host key checking during development for
  convenience; production deployments should pin the router's host key
  (see User Manual → Configuration) rather than auto-trusting it.
- CORS is enabled via Flask-CORS; restrict `origins` in `app.py` if the
  dashboard and API are ever split across different domains.

## 13. Error Handling

Every SSH-touching call in `RouterService` is wrapped so that
connection failures raise a single `RouterConnectionError`, caught at
the top of each `get_*` method. Failures produce a fully-formed JSON
payload (`status: "offline"`, `error: "<message>"`, all metric fields
`null`) rather than a stack trace, and the Flask routes translate this
into an HTTP `503`. The frontend interprets any non-2xx response, or a
network-level fetch failure, as "Offline" and updates the status badge
accordingly — it never assumes stale data is still current.

## 14. Testing Approach

The implementation was validated end-to-end against a real local SSH
server (not just mocked):

1. Verified all four endpoints return graceful `503`/offline JSON when
   no router is configured or reachable.
2. Stood up a real `sshd` instance and pointed `RouterService` at it via
   `.env`, confirming that `/api/system`, `/api/processes`, and
   `/api/network` correctly parse real `/proc/stat`, `free -m`, `ps`,
   and `ip -o addr show` / `ip route show default` output.
3. Killed the SSH server mid-session and confirmed the app detected the
   drop and returned a structured "offline" response instead of
   crashing, exercising the auto-reconnect/retry path.
4. Fixed one real bug found during this process: the initial
   `ip -o addr show` parser assumed a colon after the interface name,
   which real `ip -o` output does not include — corrected and re-verified.

## 15. Challenges Encountered

- **BusyBox/Buildroot command variability.** Flags and column sets for
  `ps`, `free`, and `ip`/`ifconfig` differ from a typical desktop Linux
  distribution. The service uses fallback command chains and multiple
  output-shape parsers rather than assuming one fixed format.
- **CPU % without `top`.** `top` output formatting is one of the least
  portable things across BusyBox builds, so CPU usage is derived
  directly from `/proc/stat` deltas instead.
- **Parsing brittleness.** Real device output rarely matches
  documentation exactly (see the `ip -o addr show` bug found during
  testing) — the parsers were written defensively and verified against
  live command output rather than assumed formats.

## 16. Future Improvements

- Pin the router's SSH host key instead of `AutoAddPolicy` for production use.
- Add authentication to the dashboard itself (it currently assumes a trusted internal network).
- Add per-interface traffic-rate graphs (bytes/sec) using `/proc/net/dev` deltas.
- Add a "kill process" action — deliberately out of scope for this monitoring-only build, but would need explicit new safeguards and sign-off before being added.
- Package the app as a systemd service with a `Dockerfile` for consistent deployment.

## 17. Conclusion

Router Task Manager delivers a working, tested, read-only monitoring
dashboard for a Buildroot-based ConnectCo router, built on the requested
Flask/Paramiko/Bootstrap/Chart.js stack, with defensive parsing for the
command-output variability typical of embedded Linux devices, and
verified end-to-end against a live SSH target rather than only unit-level assumptions.
