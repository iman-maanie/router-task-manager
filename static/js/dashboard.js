/**
 * dashboard.js
 *
 * Polls the Flask backend every REFRESH_INTERVAL_MS and updates the
 * dashboard in place (no page reload). The browser only ever talks to
 * Flask endpoints under /api/* -- it has no knowledge of SSH or router
 * credentials.
 */

let cpuChart, memChart;
let processTable;

const MAX_CHART_POINTS = 30;

function initCharts() {
  const cpuCtx = document.getElementById("cpuChart").getContext("2d");
  const memCtx = document.getElementById("memChart").getContext("2d");

  const chartOptions = {
    responsive: true,
    animation: false,
    scales: {
      y: { min: 0, max: 100, ticks: { callback: (v) => v + "%" } },
      x: { display: false },
    },
    plugins: { legend: { display: false } },
  };

  cpuChart = new Chart(cpuCtx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          data: [],
          borderColor: "#2563eb",
          backgroundColor: "rgba(37, 99, 235, 0.12)",
          fill: true,
          tension: 0.3,
          pointRadius: 0,
        },
      ],
    },
    options: chartOptions,
  });

  memChart = new Chart(memCtx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          data: [],
          borderColor: "#16a34a",
          backgroundColor: "rgba(22, 163, 74, 0.12)",
          fill: true,
          tension: 0.3,
          pointRadius: 0,
        },
      ],
    },
    options: chartOptions,
  });
}

function initProcessTable() {
  processTable = $("#processTable").DataTable({
    data: [],
    columns: [
      { data: "pid" },
      { data: "user" },
      { data: "name" },
      {
        data: "cpu_percent",
        render: (val) => (val === null || val === undefined ? "—" : val.toFixed(1) + "%"),
      },
      {
        data: "mem_percent",
        render: (val) => (val === null || val === undefined ? "—" : val.toFixed(1) + "%"),
      },
      { data: "elapsed", render: (val) => val || "—" },
    ],
    order: [[3, "desc"]],
    pageLength: 15,
    lengthMenu: [10, 15, 25, 50, 100],
    rowCallback: function (row, data) {
      $(row).find("td:eq(3)").removeClass("cpu-high cpu-medium");
      if (data.cpu_percent >= 50) {
        $(row).find("td:eq(3)").addClass("cpu-high");
      } else if (data.cpu_percent >= 20) {
        $(row).find("td:eq(3)").addClass("cpu-medium");
      }
    },
  });
}

function setStatusBadge(online) {
  const badge = document.getElementById("statusBadge");
  badge.classList.remove("status-online", "status-offline", "status-unknown");
  if (online) {
    badge.textContent = "Online";
    badge.classList.add("status-online");
  } else {
    badge.textContent = "Offline";
    badge.classList.add("status-offline");
  }
}

function updateSystem(data) {
  const online = data.status === "online";
  setStatusBadge(online);
  document.getElementById("statusValue").textContent = online ? "Online" : "Offline";

  if (!online) {
    return;
  }

  document.getElementById("hostnameLabel").textContent = data.hostname || "—";
  document.getElementById("cpuValue").textContent = data.cpu_percent + "%";
  document.getElementById("cpuBar").style.width = data.cpu_percent + "%";

  document.getElementById("ramValue").textContent = data.ram_percent + "%";
  document.getElementById("ramBar").style.width = data.ram_percent + "%";
  document.getElementById("ramDetail").textContent =
    data.ram_used_mb + " / " + data.ram_total_mb + " MB";

  document.getElementById("uptimeValue").textContent = data.uptime_human || "—";
  document.getElementById("kernelValue").textContent = "Kernel: " + (data.kernel_version || "—");
  document.getElementById("buildrootValue").textContent =
    "Buildroot: " + (data.buildroot_version || "—");

  document.getElementById("sysHostname").textContent = data.hostname || "—";
  document.getElementById("sysOs").textContent = data.buildroot_version || "—";
  document.getElementById("sysKernel").textContent = data.kernel_version || "—";
  document.getElementById("sysBuildroot").textContent = data.buildroot_version || "—";

  updateChart(cpuChart, data.cpu_history);
  updateChart(memChart, data.ram_history);
}

function updateChart(chart, history) {
  if (!history || !history.length) return;
  const points = history.slice(-MAX_CHART_POINTS);
  chart.data.labels = points.map((_, i) => i);
  chart.data.datasets[0].data = points;
  chart.update();
}

function updateProcesses(data) {
  if (data.status !== "online") {
    return;
  }
  processTable.clear();
  processTable.rows.add(data.processes);
  processTable.draw(false);
  document.getElementById("processCount").textContent = data.processes.length + " processes";
}

function updateNetwork(data) {
  if (data.status !== "online") {
    return;
  }
  document.getElementById("gatewayValue").textContent = data.default_gateway || "Unknown";

  const container = document.getElementById("interfacesList");
  container.innerHTML = "";

  data.interfaces.forEach((iface) => {
    const block = document.createElement("div");
    block.className = "interface-block";
    const ips = iface.ip_addresses.length ? iface.ip_addresses.join(", ") : "No address";
    block.innerHTML = `
      <div class="interface-name">${iface.name}</div>
      <div>IP: ${ips}</div>
      <div>MAC: ${iface.mac_address || "Unknown"}</div>
    `;
    container.appendChild(block);
  });
}

async function fetchJson(url) {
  const response = await fetch(url);
  return response.json();
}

async function refreshAll() {
  try {
    const [system, processes, network] = await Promise.all([
      fetchJson("/api/system"),
      fetchJson("/api/processes"),
      fetchJson("/api/network"),
    ]);

    updateSystem(system);
    updateProcesses(processes);
    updateNetwork(network);
  } catch (err) {
    setStatusBadge(false);
    console.error("Dashboard refresh failed:", err);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initCharts();
  initProcessTable();
  refreshAll();
  setInterval(refreshAll, REFRESH_INTERVAL_MS);
});
