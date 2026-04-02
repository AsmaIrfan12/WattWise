import { AdminApiClient, ApiError } from "./api-client.js";

const api = new AdminApiClient();
let energyChartInstance = null;

function sanitize(str) {
  return typeof DOMPurify !== "undefined" ? DOMPurify.sanitize(String(str ?? "")) : String(str ?? "").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
let adminEmail = localStorage.getItem("ww_email") || "";

const overlay = document.getElementById("login-overlay");
const loginEmail = document.getElementById("l-email");
const loginPass = document.getElementById("l-pass");
const loginBtn = document.getElementById("l-btn");
const loginErr = document.getElementById("l-err");
const loggedAs = document.getElementById("logged-as");

function showLogin() {
  overlay.style.display = "flex";
  loginEmail.value = adminEmail;
  loginErr.style.display = "none";
}

function hideLogin() {
  overlay.style.display = "none";
  loggedAs.textContent = adminEmail;
}

function toast(message, isError = false) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.style.background = isError ? "#ef4444" : "#16a34a";
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 3000);
}

function formatN(value, digits = 0) {
  return Number(value || 0).toFixed(digits);
}

async function onLogin() {
  const email = loginEmail.value.trim();
  const password = loginPass.value;

  loginErr.style.display = "none";
  loginBtn.textContent = "Signing in...";

  try {
    const response = await api.login({ email, password });
    if (!response.is_admin) {
      throw new Error("This account does not have admin access.");
    }

    api.setToken(response.access_token);
    adminEmail = email;
    localStorage.setItem("ww_email", email);
    hideLogin();
    await loadDashboard();
  } catch (error) {
    loginErr.textContent = error instanceof Error ? error.message : "Login failed";
    loginErr.style.display = "block";
  } finally {
    loginBtn.textContent = "Sign In";
  }
}

function onLogout() {
  api.clearToken();
  localStorage.removeItem("ww_email");
  adminEmail = "";
  showLogin();
}

function handleApiError(error, fallback = "Request failed") {
  if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
    showLogin();
    toast("Session expired - please sign in again", true);
    return;
  }
  toast(error instanceof Error ? error.message : fallback, true);
}

async function loadDashboard() {
  try {
    const d = await api.getDashboard();
    document.getElementById("stat-users").textContent = `${d.total_users}`;
    document.getElementById("s-active").textContent = `${d.active_users_today} active today`;
    document.getElementById("s-homes").textContent = `${d.total_homes}`;
    document.getElementById("s-energy").textContent = `${formatN(d.energy_today_kwh, 2)} kWh`;
    document.getElementById("s-cost").textContent = `£${formatN(d.cost_today_gbp, 2)}`;
    document.getElementById("s-goal").textContent = `${formatN(d.avg_goal_adherence_pct, 0)}%`;
    document.getElementById("s-notifs").textContent = `${d.notifications_sent_today}`;
    document.getElementById("s-dec").textContent = `${d.decisions_recorded_today}`;
  } catch {
    // Keep placeholder values if dashboard query fails.
  }

  try {
    const rows = await api.getEnergyAnalytics(7);
    const labels = rows.map((r) => r.date || "");
    const data = rows.map((r) => r.total_kwh || 0);
    renderEnergyChart(labels, data);
  } catch {
    renderEnergyChart(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], [4.0, 6.5, 5.0, 8.0, 7.0, 9.0, 5.5]);
  }

  try {
    const impact = await api.getDecisionAnalytics();
    document.getElementById("impact-tbl").innerHTML = `
      <tr><td style="color:var(--muted)">Total Decisions</td><td>${sanitize(impact.total_decisions || 0)}</td></tr>
      <tr><td style="color:var(--muted)">Energy Saved</td><td>${sanitize(formatN(impact.total_energy_saved_kwh, 2))} kWh</td></tr>
      <tr><td style="color:var(--muted)">Cost Saved</td><td>£${sanitize(formatN(impact.total_cost_saved_gbp, 2))}</td></tr>
      <tr><td style="color:var(--muted)">Avg Effectiveness</td><td>${sanitize(formatN(impact.avg_effectiveness_score, 0))}%</td></tr>
    `;
  } catch {
    // No-op; keep default loading row.
  }
}

function renderEnergyChart(labels, data) {
  const ctx = document.getElementById("energyChart");
  if (!ctx) return;
  if (energyChartInstance) energyChartInstance.destroy();
  energyChartInstance = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "kWh",
        data,
        backgroundColor: "rgba(22, 163, 74, 0.7)",
        borderColor: "#16a34a",
        borderWidth: 1,
        borderRadius: 4,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (c) => `${c.parsed.y.toFixed(2)} kWh` } },
      },
      scales: {
        y: { beginAtZero: true, grid: { color: "rgba(255,255,255,0.05)" }, ticks: { color: "#94a3b8" } },
        x: { grid: { display: false }, ticks: { color: "#94a3b8" } },
      },
    },
  });
}

async function loadUsers() {
  try {
    const users = await api.getUsers();
    document.getElementById("users-tbl").innerHTML = users
      .map(
        (u) => `
      <tr><td>${sanitize(u.name)}</td><td style="color:var(--muted)">${sanitize(u.email)}</td>
      <td>${u.last_login_at ? new Date(u.last_login_at).toLocaleDateString("en-GB") : "Never"}</td>
      <td>${u.notifications_enabled ? "✅" : "❌"}</td></tr>`
      )
      .join("");
  } catch (error) {
    handleApiError(error, "Unable to load users");
    document.getElementById("users-tbl").innerHTML =
      '<tr><td colspan="4" style="color:var(--muted)">Auth required</td></tr>';
  }
}

async function loadRankings() {
  try {
    const rows = await api.getRankings();
    document.getElementById("rank-tbl").innerHTML = rows
      .map(
        (r) => `
      <tr><td><strong>#${sanitize(r.rank)}</strong></td><td>${sanitize(r.user_name)}</td>
      <td><strong>${sanitize(formatN(r.score, 1))}</strong></td><td>${sanitize(formatN(r.efficiency, 0))}%</td>
      <td>${sanitize(formatN(r.goal_adherence, 0))}%</td>
      <td>${sanitize(formatN(r.total_kwh, 2))}</td><td>£${sanitize(formatN(r.cost_gbp, 2))}</td></tr>`
      )
      .join("");
  } catch {
    document.getElementById("rank-tbl").innerHTML =
      '<tr><td colspan="7" style="color:var(--muted)">No rankings yet</td></tr>';
  }
}

async function loadAnalytics() {
  try {
    const rows = await api.getEnergyAnalytics(14);
    document.getElementById("analytics-tbl").innerHTML = rows
      .map(
        (r) => `
      <tr><td>${r.date}</td><td>${formatN(r.total_kwh, 2)}</td>
      <td>£${formatN(r.total_cost_gbp, 2)}</td><td>${r.active_homes}</td></tr>`
      )
      .join("");
  } catch (error) {
    handleApiError(error, "Unable to load analytics");
  }
}

async function loadDecisions() {
  try {
    const d = await api.getDecisionAnalytics();
    document.getElementById("d-total").textContent = `${d.total_decisions || 0}`;
    document.getElementById("d-acc").textContent = `${d.accepted || 0}`;
    document.getElementById("d-rej").textContent = `${d.rejected || 0}`;
    document.getElementById("d-rsp").textContent = `${formatN(d.avg_response_time_seconds, 0)} s`;
    document.getElementById("d-kwh").textContent = `${formatN(d.total_energy_saved_kwh, 2)} kWh`;
    document.getElementById("d-eff").textContent = `${formatN(d.avg_effectiveness_score, 0)}%`;
  } catch (error) {
    handleApiError(error, "Unable to load decisions");
  }
}

async function sendNotification() {
  const title = document.getElementById("n-title").value.trim();
  const message = document.getElementById("n-msg").value.trim();

  if (!title || !message) {
    toast("Title and message required", true);
    return;
  }

  let userIds = null;
  if (document.getElementById("n-target").value === "custom") {
    userIds = document
      .getElementById("n-ids")
      .value.split(",")
      .map((v) => parseInt(v.trim(), 10))
      .filter((v) => Number.isInteger(v) && v > 0);
  }

  try {
    const result = await api.sendNotification({
      title,
      message,
      severity: document.getElementById("n-sev").value,
      action_hint: document.getElementById("n-hint").value.trim() || null,
      requires_user_action: document.getElementById("n-action").checked,
      user_ids: userIds,
    });

    toast(`Sent to ${result.notifications_sent} user(s)`);
    document.getElementById("n-title").value = "";
    document.getElementById("n-msg").value = "";
  } catch (error) {
    handleApiError(error, "Unable to send notification");
  }
}

const loaders = {
  dashboard: loadDashboard,
  users: loadUsers,
  rankings: loadRankings,
  analytics: loadAnalytics,
  decisions: loadDecisions,
  backup: loadBackupSection,
};

function setupNavigation() {
  document.querySelectorAll("nav a").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      const section = link.dataset.section;
      document.querySelectorAll("section").forEach((s) => s.classList.remove("active"));
      document.querySelectorAll("nav a").forEach((a) => a.classList.remove("active"));
      document.getElementById(`s-${section}`).classList.add("active");
      link.classList.add("active");
      const loader = loaders[section];
      if (loader) {
        loader();
      }
    });
  });
}

function setupFormHandlers() {
  document.getElementById("n-target").addEventListener("change", function onChange() {
    document.getElementById("n-ids-group").style.display = this.value === "custom" ? "block" : "none";
  });

  document.getElementById("send-btn").addEventListener("click", sendNotification);
}

function setupAuthHandlers() {
  loginBtn.addEventListener("click", onLogin);
  loginPass.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      onLogin();
    }
  });
  document.getElementById("logout-btn").addEventListener("click", onLogout);
}

function setupClock() {
  const el = document.getElementById("clock");
  const tick = () => {
    el.textContent = new Date().toLocaleTimeString("en-GB");
  };
  tick();
  setInterval(tick, 1000);
}

function init() {
  setupNavigation();
  setupFormHandlers();
  setupAuthHandlers();
  setupClock();

  if (!api.hasToken()) {
    showLogin();
    return;
  }

  hideLogin();
  loadDashboard();
}

init();

// ── Backup Section ────────────────────────────────────────────

async function loadBackupSection() {
  try {
    const s = await api.getBackupSettings();
    const toggle = document.getElementById("backup-toggle");
    const label = document.getElementById("backup-toggle-label");
    const stats = document.getElementById("backup-stats");
    toggle.checked = s.enabled;
    label.textContent = s.enabled ? "Enabled" : "Disabled";
    const lastFile = s.last_backup_file
      ? `Last: ${s.last_backup_file} (${s.last_backup_size_mb ?? "?"} MB)`
      : "No backups yet";
    stats.textContent = `${s.backup_count} archive(s) stored. ${lastFile}`;
    if (s.warning) stats.textContent += ` — ${s.warning}`;

    const newToggle = toggle.cloneNode(true);
    newToggle.checked = s.enabled;
    toggle.parentNode.replaceChild(newToggle, toggle);
    newToggle.addEventListener("change", async () => {
      try {
        const res = await api.setBackupSettings({ enabled: newToggle.checked });
        label.textContent = res.enabled ? "Enabled" : "Disabled";
        toast(res.message);
      } catch (e) {
        toast(`Failed: ${e.message}`, true);
        newToggle.checked = !newToggle.checked;
      }
    });
  } catch (e) {
    document.getElementById("backup-stats").textContent = `Error: ${e.message}`;
  }

  try {
    const files = await api.listBackups();
    const tbody = document.getElementById("backup-list-body");
    if (!files.length) {
      tbody.innerHTML = '<tr><td colspan="3" style="color:var(--muted)">No backups stored yet.</td></tr>';
    } else {
      tbody.innerHTML = files.map(f => `
        <tr>
          <td style="font-family:monospace;font-size:.78rem">${sanitize(f.name)}</td>
          <td>${f.size_mb} MB</td>
          <td>${new Date(f.created_at).toLocaleString()}</td>
        </tr>
      `).join("");
    }
  } catch (e) {
    document.getElementById("backup-list-body").innerHTML =
      `<tr><td colspan="3" style="color:var(--muted)">Error: ${sanitize(e.message)}</td></tr>`;
  }

  document.getElementById("backup-download-btn").onclick = downloadBackupNow;
}

async function downloadBackupNow() {
  const btn = document.getElementById("backup-download-btn");
  const status = document.getElementById("backup-download-status");
  btn.disabled = true;
  btn.textContent = "Generating…";
  status.textContent = "Running mysqldump — this may take a moment…";
  try {
    const res = await fetch("/api/admin/backup/download", {
      headers: { Authorization: `Bearer ${api.token}` },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Unknown error" }));
      throw new Error(err.detail || "Download failed");
    }
    const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition") || "";
    const match = cd.match(/filename="?([^"]+)"?/);
    const fname = match ? match[1] : `wattwise-backup-${Date.now()}.sql.gz`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = fname;
    a.click();
    URL.revokeObjectURL(url);
    status.textContent = `Downloaded: ${sanitize(fname)}`;
    toast("Backup downloaded successfully");
    loadBackupSection();
  } catch (e) {
    status.textContent = `Error: ${e.message}`;
    toast(`Backup failed: ${e.message}`, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "Download Backup Now";
  }
}
