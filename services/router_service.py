"""
services/router_service.py

RouterService encapsulates ALL communication with the ConnectCo router.
It is the only part of the application that ever opens an SSH session.

Responsibilities:
    * Open / reuse / automatically re-establish an SSH connection (Paramiko)
    * Run READ-ONLY diagnostic commands on the router
    * Parse the raw text output of BusyBox / Buildroot commands into
      clean Python data structures
    * Never execute anything that could change router configuration
    * Fail gracefully and return structured error information instead
      of raising exceptions up to the Flask routes

This class deliberately only ever runs a fixed allow-list of read-only
commands (see ALLOWED_COMMANDS). There is no code path that accepts
arbitrary command strings from the frontend.
"""

import re
import socket
import threading
import time
from collections import deque

import paramiko

from config import Config


class RouterConnectionError(Exception):
    """Raised when the router cannot be reached over SSH."""


class RouterService:
    """
    Thread-safe wrapper around a single Paramiko SSH connection to the
    router. Automatically reconnects if the connection has dropped.

    This service is MONITORING ONLY. Every command it issues is read-only
    (ps, cat /proc/..., free, uptime, ip addr, uname, etc.). It never
    writes to router configuration files and never restarts services.
    """

    def __init__(self):
        self._client: paramiko.SSHClient | None = None
        self._lock = threading.Lock()
        self._last_error: str | None = None
        self._cpu_history = deque(maxlen=Config.CPU_HISTORY_LENGTH)
        self._mem_history = deque(maxlen=Config.CPU_HISTORY_LENGTH)
        # Previous /proc/stat sample, used to compute CPU % over an interval
        self._prev_cpu_sample = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _is_connected(self) -> bool:
        if self._client is None:
            return False
        transport = self._client.get_transport()
        return bool(transport and transport.is_active())

    def _connect(self):
        """Open a new SSH connection using key auth if available, else password."""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = dict(
            hostname=Config.ROUTER_HOST,
            port=Config.ROUTER_PORT,
            username=Config.ROUTER_USERNAME,
            timeout=Config.SSH_CONNECT_TIMEOUT,
            banner_timeout=Config.SSH_CONNECT_TIMEOUT,
            auth_timeout=Config.SSH_CONNECT_TIMEOUT,
        )

        if Config.ROUTER_KEY_PATH:
            connect_kwargs["key_filename"] = Config.ROUTER_KEY_PATH
        elif Config.ROUTER_PASSWORD:
            connect_kwargs["password"] = Config.ROUTER_PASSWORD
        else:
            raise RouterConnectionError(
                "No ROUTER_PASSWORD or ROUTER_KEY_PATH configured in .env"
            )

        client.connect(**connect_kwargs)
        self._client = client
        self._last_error = None

    def _ensure_connected(self):
        """Reconnect automatically if the session is missing or dead."""
        with self._lock:
            if self._is_connected():
                return
            try:
                self._connect()
            except (paramiko.SSHException, socket.error, OSError) as exc:
                self._last_error = str(exc)
                self._client = None
                raise RouterConnectionError(str(exc)) from exc

    def close(self):
        with self._lock:
            if self._client is not None:
                try:
                    self._client.close()
                except Exception:
                    pass
                self._client = None

    # ------------------------------------------------------------------
    # Low-level command execution (read-only only)
    # ------------------------------------------------------------------

    def _run(self, command: str) -> str:
        """
        Execute a single read-only command on the router and return stdout.
        Retries once after reconnecting if the first attempt fails.
        """
        for attempt in (1, 2):
            try:
                self._ensure_connected()
                stdin, stdout, stderr = self._client.exec_command(
                    command, timeout=Config.SSH_COMMAND_TIMEOUT
                )
                stdin.close()
                out = stdout.read().decode("utf-8", errors="replace")
                stdout.channel.recv_exit_status()
                return out
            except (paramiko.SSHException, socket.error, OSError, EOFError) as exc:
                self._last_error = str(exc)
                self._client = None  # force reconnect on next attempt
                if attempt == 2:
                    raise RouterConnectionError(str(exc)) from exc
                time.sleep(0.3)
        return ""

    def _run_first_success(self, commands: list[str]) -> str:
        """Try a list of fallback commands until one returns non-empty output."""
        last_output = ""
        for cmd in commands:
            try:
                out = self._run(cmd)
                if out and out.strip():
                    return out
                last_output = out
            except RouterConnectionError:
                raise
            except Exception:
                continue
        return last_output

    def check_health(self) -> dict:
        """Lightweight connectivity check used by /api/health."""
        try:
            self._run("echo ok")
            return {"status": "online", "error": None}
        except RouterConnectionError as exc:
            return {"status": "offline", "error": str(exc)}

    # ------------------------------------------------------------------
    # System overview
    # ------------------------------------------------------------------

    def get_system_overview(self) -> dict:
        try:
            cpu_percent = self._get_cpu_percent()
            mem = self._get_memory()
            uptime_seconds, uptime_human = self._get_uptime()
            hostname = self._get_hostname()
            kernel = self._run("uname -r").strip() or "Unknown"
            buildroot_version = self._get_buildroot_version()

            self._cpu_history.append(cpu_percent)
            self._mem_history.append(mem["percent"])

            return {
                "status": "online",
                "cpu_percent": cpu_percent,
                "cpu_history": list(self._cpu_history),
                "ram_percent": mem["percent"],
                "ram_total_mb": mem["total_mb"],
                "ram_used_mb": mem["used_mb"],
                "ram_free_mb": mem["free_mb"],
                "ram_history": list(self._mem_history),
                "uptime_seconds": uptime_seconds,
                "uptime_human": uptime_human,
                "hostname": hostname,
                "kernel_version": kernel,
                "buildroot_version": buildroot_version,
                "error": None,
            }
        except RouterConnectionError as exc:
            return self._offline_system_payload(str(exc))

    def _offline_system_payload(self, error_message: str) -> dict:
        return {
            "status": "offline",
            "cpu_percent": None,
            "cpu_history": list(self._cpu_history),
            "ram_percent": None,
            "ram_total_mb": None,
            "ram_used_mb": None,
            "ram_free_mb": None,
            "ram_history": list(self._mem_history),
            "uptime_seconds": None,
            "uptime_human": None,
            "hostname": None,
            "kernel_version": None,
            "buildroot_version": None,
            "error": error_message,
        }

    def _get_cpu_percent(self) -> float:
        """
        Compute CPU usage % from /proc/stat deltas (works on BusyBox/Buildroot
        without relying on 'top', whose output format varies a lot).
        """
        raw = self._run("cat /proc/stat")
        first_line = raw.splitlines()[0] if raw else ""
        parts = first_line.split()

        if not parts or parts[0] != "cpu":
            return 0.0

        values = list(map(int, parts[1:]))
        # user, nice, system, idle, iowait, irq, softirq, steal (fields vary by kernel)
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)

        sample = {"idle": idle, "total": total}

        if self._prev_cpu_sample is None:
            self._prev_cpu_sample = sample
            # No delta available yet on first call; take a very short second sample.
            time.sleep(0.3)
            raw2 = self._run("cat /proc/stat")
            parts2 = (raw2.splitlines()[0] if raw2 else "").split()
            if parts2 and parts2[0] == "cpu":
                values2 = list(map(int, parts2[1:]))
                idle2 = values2[3] + (values2[4] if len(values2) > 4 else 0)
                total2 = sum(values2)
                sample = {"idle": idle2, "total": total2}

        prev = self._prev_cpu_sample
        self._prev_cpu_sample = sample

        delta_total = sample["total"] - prev["total"]
        delta_idle = sample["idle"] - prev["idle"]

        if delta_total <= 0:
            return 0.0

        usage = (1 - (delta_idle / delta_total)) * 100
        return round(max(0.0, min(100.0, usage)), 1)

    def _get_memory(self) -> dict:
        raw = self._run("free -m") or self._run("cat /proc/meminfo")

        # Try 'free -m' style output first
        match = re.search(
            r"Mem:\s+(\d+)\s+(\d+)\s+(\d+)", raw, re.IGNORECASE
        )
        if match:
            total, used, free = map(int, match.groups())
            percent = round((used / total) * 100, 1) if total else 0.0
            return {
                "total_mb": total,
                "used_mb": used,
                "free_mb": free,
                "percent": percent,
            }

        # Fallback: parse /proc/meminfo (values are in kB)
        def _kb(field):
            m = re.search(rf"{field}:\s+(\d+)\s*kB", raw)
            return int(m.group(1)) if m else 0

        total_kb = _kb("MemTotal")
        free_kb = _kb("MemFree") + _kb("Buffers") + _kb("Cached")
        used_kb = max(total_kb - free_kb, 0)
        total_mb = total_kb // 1024
        percent = round((used_kb / total_kb) * 100, 1) if total_kb else 0.0

        return {
            "total_mb": total_mb,
            "used_mb": used_kb // 1024,
            "free_mb": free_kb // 1024,
            "percent": percent,
        }

    def _get_uptime(self):
        raw = self._run("cat /proc/uptime").strip()
        try:
            seconds = float(raw.split()[0])
        except (ValueError, IndexError):
            return None, "Unknown"

        seconds = int(seconds)
        days, rem = divmod(seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, _ = divmod(rem, 60)

        parts = []
        if days:
            parts.append(f"{days}d")
        if hours or days:
            parts.append(f"{hours}h")
        parts.append(f"{minutes}m")

        return seconds, " ".join(parts)

    def _get_hostname(self) -> str:
        raw = self._run_first_success(
            ["hostname", "cat /proc/sys/kernel/hostname"]
        ).strip()
        return raw or "Unknown"

    def _get_buildroot_version(self) -> str:
        raw = self._run_first_success(
            [
                "cat /etc/os-release",
                "cat /etc/buildroot-version",
                "cat /usr/lib/os-release",
            ]
        )
        match = re.search(r'PRETTY_NAME="?([^"\n]+)"?', raw)
        if match:
            return match.group(1).strip()
        if raw.strip():
            return raw.strip().splitlines()[0]
        return "Unknown"

    # ------------------------------------------------------------------
    # Process manager
    # ------------------------------------------------------------------

    def get_processes(self) -> dict:
        try:
            raw = self._run_first_success(
                [
                    "ps -eo pid,user,comm,%cpu,%mem,etime --no-headers",
                    "ps -eo pid,user,comm,%cpu,%mem,etime",
                    "ps -o pid,user,comm,%cpu,%mem,etime",
                    "ps aux",
                    "ps",
                ]
            )
            processes = self._parse_processes(raw)
            return {"status": "online", "processes": processes, "error": None}
        except RouterConnectionError as exc:
            return {"status": "offline", "processes": [], "error": str(exc)}

    def _parse_processes(self, raw: str) -> list[dict]:
        lines = [l for l in raw.splitlines() if l.strip()]
        if not lines:
            return []

        # Drop a header line if present (starts with PID or USER)
        if lines and re.match(r"^\s*(PID|USER)\b", lines[0], re.IGNORECASE):
            lines = lines[1:]

        processes = []
        for line in lines:
            fields = line.split()
            if not fields:
                continue

            proc = self._parse_ps_line(fields)
            if proc:
                processes.append(proc)

        return processes

    def _parse_ps_line(self, fields: list[str]) -> dict | None:
        """
        Handles a few common ps output shapes seen across BusyBox/Buildroot
        and full procps builds:

          1) PID USER COMM %CPU %MEM ETIME           (6 fields)
          2) PID USER TIME COMMAND                    (BusyBox minimal ps)
          3) USER PID %CPU %MEM VSZ RSS TTY STAT START TIME COMMAND (ps aux)
        """
        try:
            if len(fields) >= 6 and self._looks_like_pid(fields[0]):
                pid, user, comm, cpu, mem, etime = fields[:6]
                return {
                    "pid": int(pid),
                    "user": user,
                    "name": comm,
                    "cpu_percent": self._safe_float(cpu),
                    "mem_percent": self._safe_float(mem),
                    "elapsed": etime,
                }

            if len(fields) == 4 and self._looks_like_pid(fields[0]):
                pid, time_field, command = fields[0], fields[2], fields[3]
                return {
                    "pid": int(pid),
                    "user": fields[1],
                    "name": command,
                    "cpu_percent": None,
                    "mem_percent": None,
                    "elapsed": time_field,
                }

            # ps aux style: USER PID %CPU %MEM VSZ RSS TTY STAT START TIME COMMAND
            if len(fields) >= 11 and self._looks_like_pid(fields[1]):
                user = fields[0]
                pid = fields[1]
                cpu = fields[2]
                mem = fields[3]
                command = " ".join(fields[10:])
                return {
                    "pid": int(pid),
                    "user": user,
                    "name": command.split()[0] if command else "unknown",
                    "cpu_percent": self._safe_float(cpu),
                    "mem_percent": self._safe_float(mem),
                    "elapsed": fields[9],
                }
        except (ValueError, IndexError):
            return None

        return None

    @staticmethod
    def _looks_like_pid(value: str) -> bool:
        return value.isdigit()

    @staticmethod
    def _safe_float(value: str):
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    # ------------------------------------------------------------------
    # Network information
    # ------------------------------------------------------------------

    def get_network_info(self) -> dict:
        try:
            interfaces = self._get_interfaces()
            gateway = self._get_default_gateway()
            return {
                "status": "online",
                "interfaces": interfaces,
                "default_gateway": gateway,
                "error": None,
            }
        except RouterConnectionError as exc:
            return {
                "status": "offline",
                "interfaces": [],
                "default_gateway": None,
                "error": str(exc),
            }

    def _get_interfaces(self) -> list[dict]:
        raw = self._run_first_success(["ip -o addr show", "ifconfig -a"])
        if "inet" in raw and "\n" in raw and re.search(r"^\d+:", raw, re.MULTILINE):
            return self._parse_ip_addr(raw)
        return self._parse_ifconfig(raw)

    def _parse_ip_addr(self, raw: str) -> list[dict]:
        interfaces: dict[str, dict] = {}
        for line in raw.splitlines():
            m = re.match(r"^\d+:\s+(\S+?)(?:@\S+)?\s+inet6?\s", line)
            if not m:
                continue
            name = m.group(1)
            entry = interfaces.setdefault(
                name, {"name": name, "ip_addresses": [], "mac_address": None}
            )
            ip_match = re.search(r"inet6?\s+([0-9a-fA-F:.\/]+)", line)
            if ip_match:
                entry["ip_addresses"].append(ip_match.group(1))

        # MAC addresses require a separate lookup (ip -o link show)
        link_raw = self._run("ip -o link show")
        for line in link_raw.splitlines():
            m = re.match(r"^\d+:\s+(\S+?)(?:@\S+)?:", line)
            mac_match = re.search(r"link/\S+\s+([0-9a-fA-F:]{17})", line)
            if m and mac_match and m.group(1) in interfaces:
                interfaces[m.group(1)]["mac_address"] = mac_match.group(1)

        return list(interfaces.values())

    def _parse_ifconfig(self, raw: str) -> list[dict]:
        interfaces = []
        blocks = re.split(r"\n(?=\S)", raw.strip())
        for block in blocks:
            name_match = re.match(r"^(\S+?)[\s:]", block)
            if not name_match:
                continue
            name = name_match.group(1)
            ips = re.findall(r"inet6?\s?(?:addr:)?\s*([0-9a-fA-F:.]+)", block)
            mac_match = re.search(
                r"(?:HWaddr|ether)\s+([0-9a-fA-F:]{17})", block
            )
            interfaces.append(
                {
                    "name": name,
                    "ip_addresses": ips,
                    "mac_address": mac_match.group(1) if mac_match else None,
                }
            )
        return interfaces

    def _get_default_gateway(self):
        raw = self._run_first_success(
            ["ip route show default", "route -n"]
        )
        match = re.search(r"default\s+via\s+([0-9.]+)", raw)
        if match:
            return match.group(1)
        match = re.search(
            r"^\s*0\.0\.0\.0\s+([0-9.]+)", raw, re.MULTILINE
        )
        return match.group(1) if match else None
