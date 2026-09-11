# Router Task Manager — User Manual

## 1. What This Is

A web dashboard that shows you what's happening on a ConnectCo router in
real time — CPU, memory, uptime, running processes, and network info —
updated automatically every 5 seconds. It is monitoring-only: it never
changes anything on the router.

## 2. Installation

**Requirements:** Python 3.10+, network access from your machine to the
router's SSH port (usually 22).

```bash
cd router-task-manager
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 3. Configuration

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```
2. Open `.env` and fill in your router's details:

   ```
   ROUTER_HOST=192.168.1.1
   ROUTER_PORT=22
   ROUTER_USERNAME=root
   ```

3. Choose **one** authentication method:
   - **SSH key (recommended):** set `ROUTER_KEY_PATH=/path/to/private_key`
     and leave `ROUTER_PASSWORD` blank.
   - **Password:** set `ROUTER_PASSWORD=yourpassword` and leave
     `ROUTER_KEY_PATH` blank.

4. `.env` is only ever read by the Flask backend — it is never sent to
   the browser and should not be committed to version control.

## 4. Logging Into the Router (first-time SSH trust)

The first time the app connects, it will trust the router's SSH host
key automatically (via Paramiko's `AutoAddPolicy`). If you'd rather
verify the host key yourself first, you can test the connection
manually before starting the app:

```bash
ssh -p 22 root@192.168.1.1
```

If that connects, the app's credentials in `.env` are correct.

## 5. Starting the Application

```bash
python3 app.py
```

By default the server listens on `http://0.0.0.0:5000`. You can change
the host/port in `.env` (`FLASK_HOST`, `FLASK_PORT`).

## 6. Opening the Dashboard

Open a browser to:

```
http://localhost:5000
```

(or the IP address of the machine running the Flask app, if accessing
from another computer on the network).

You should see:
- Four summary cards: CPU Usage, RAM Usage, Uptime, Router Status
- CPU and Memory history charts
- A searchable/sortable/paginated table of running processes
- Network information (interfaces, IPs, MACs, default gateway)
- System information (hostname, OS, kernel, Buildroot version)

Everything refreshes automatically every 5 seconds — no need to reload
the page.

## 7. Troubleshooting

**Dashboard shows "Offline" everywhere:**
- Confirm `ROUTER_HOST` / `ROUTER_PORT` in `.env` are correct.
- Confirm the machine running Flask can actually reach the router
  (try `ssh` manually, as in step 4).
- Check `ROUTER_USERNAME` and either `ROUTER_PASSWORD` or
  `ROUTER_KEY_PATH` are set correctly (only one auth method is needed).
- Look at the Flask terminal output — connection errors are logged
  there.

**Process table is empty or missing CPU/Memory columns:**
- Some minimal BusyBox `ps` builds only report PID, user, elapsed time,
  and command name. The app falls back automatically, but CPU%/Mem%
  will show as "—" on very minimal `ps` implementations. This is a
  router-firmware limitation, not an app bug.

**Network panel shows no interfaces:**
- The app tries `ip -o addr show` first, then `ifconfig -a`. If neither
  tool exists on the router's PATH for the SSH user, no interfaces can
  be listed. Check `which ip ifconfig` over SSH on the router directly.

**Port 5000 already in use:**
- Change `FLASK_PORT` in `.env` to an unused port (e.g. `5050`).

**Charts appear flat / at zero for the first refresh:**
- This is expected — CPU usage is computed from the *difference*
  between two samples, so the very first reading may read low until a
  second data point arrives a few seconds later.
