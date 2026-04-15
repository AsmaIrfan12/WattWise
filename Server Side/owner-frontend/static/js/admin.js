/**
 * WattWise Admin Command Centre — JavaScript
 * Author: Mr. Suhas Devmane, Cardiff University, UK
 * =================================================
 * Handles: auth, navigation, dashboard KPIs, charts,
 * user management, personas, analytics, notifications,
 * device status, audit log, backups, bulk operations.
 */

'use strict';

// ── Config & State ──────────────────────────────────────────
const API_BASE = '';  // Same-origin via nginx
let _token = null;
let _currentPage = { users: 1 };
let _selectedUserIds = new Set();
let _charts = {};
let _personaColors = {
  'Eco Champion':    '#10b981',
  'Active Improver': '#3b82f6',
  'Steady User':     '#8b5cf6',
  'High Consumer':   '#f59e0b',
  'Disengaged':      '#6b7280',
};
let _personaBadgeClass = {
  'Eco Champion':    'eco',
  'Active Improver': 'improver',
  'Steady User':     'steady',
  'High Consumer':   'high',
  'Disengaged':      'diseng',
};

// ── API Helper ──────────────────────────────────────────────
async function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (_token) headers['Authorization'] = `Bearer ${_token}`;
  const res = await fetch(`${API_BASE}${path}`, { headers, ...opts });
  if (res.status === 401) { doLogout(); return null; }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  if (res.status === 204) return {};
  return res.json();
}

// ── Auth ─────────────────────────────────────────────────────
function getToken() {
  return sessionStorage.getItem('ww_admin_token');
}

async function checkAuth() {
  _token = getToken();
  if (!_token) { showLoginOverlay(); return false; }
  try {
    const me = await api('/api/auth/me');
    if (!me?.is_admin) { doLogout(); return false; }
    document.getElementById('admin-name').textContent = `👤 ${DOMPurify.sanitize(me.name)}`;
    return true;
  } catch {
    doLogout(); return false;
  }
}

function showLoginOverlay() {
  document.body.innerHTML = `
    <div style="
      min-height:100vh; display:flex; align-items:center; justify-content:center;
      background:#0b0f1a; font-family:Inter,sans-serif;
    ">
      <div style="
        width:380px; background:#111827; border:1px solid rgba(255,255,255,0.07);
        border-radius:16px; padding:40px; box-shadow:0 20px 60px rgba(0,0,0,0.5);
      ">
        <div style="text-align:center; margin-bottom:32px;">
          <div style="font-size:48px; margin-bottom:12px;">⚡</div>
          <div style="font-size:22px; font-weight:800;
            background:linear-gradient(135deg,#60a5fa,#a78bfa);
            -webkit-background-clip:text; -webkit-text-fill-color:transparent;
            background-clip:text;">WattWise Admin</div>
          <div style="font-size:13px; color:#6b7280; margin-top:6px;">Command Centre</div>
        </div>
        <form id="login-form">
          <input id="login-email" type="email" placeholder="Admin email"
            style="width:100%; padding:12px 16px; background:#1a2234; border:1px solid rgba(255,255,255,0.07);
            border-radius:8px; color:#f1f5f9; font-size:14px; margin-bottom:12px; font-family:inherit; box-sizing:border-box;"
            required/>
          <input id="login-pass" type="password" placeholder="Password"
            style="width:100%; padding:12px 16px; background:#1a2234; border:1px solid rgba(255,255,255,0.07);
            border-radius:8px; color:#f1f5f9; font-size:14px; margin-bottom:20px; font-family:inherit; box-sizing:border-box;"
            required/>
          <button type="submit"
            style="width:100%; padding:12px; background:#3b82f6; color:#fff; border:none; border-radius:8px;
            font-size:15px; font-weight:700; cursor:pointer; font-family:inherit;">
            Sign In
          </button>
          <div id="login-error" style="color:#ef4444; font-size:13px; text-align:center; margin-top:12px; min-height:18px;"></div>
        </form>
      </div>
    </div>`;

  document.getElementById('login-form').addEventListener('submit', async e => {
    e.preventDefault();
    const errEl = document.getElementById('login-error');
    errEl.textContent = '';
    try {
      const data = await api('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({
          email: document.getElementById('login-email').value,
          password: document.getElementById('login-pass').value,
        }),
      });
      if (!data.is_admin) { errEl.textContent = 'Access denied: not an admin account.'; return; }
      sessionStorage.setItem('ww_admin_token', data.access_token);
      location.reload();
    } catch (err) {
      errEl.textContent = err.message || 'Login failed';
    }
  });
}

function doLogout() {
  api('/api/auth/logout', { method: 'POST' }).catch(() => {});
  sessionStorage.removeItem('ww_admin_token');
  location.reload();
}

// ── Navigation ──────────────────────────────────────────────
function navigateTo(section) {
  document.querySelectorAll('.section').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
  const sec = document.getElementById(`section-${section}`);
  if (sec) sec.classList.add('active');
  const nav = document.getElementById(`nav-${section}`);
  if (nav) nav.classList.add('active');

  const titles = {
    dashboard: 'Dashboard', users: 'User Management', personas: 'Persona Groups',
    rankings: 'Community Rankings', analytics: 'Analytics', devices: 'Device Status',
    notifications: 'Notifications', backup: 'Backups', audit: 'Audit Log',
  };
  document.getElementById('page-title').textContent = titles[section] || section;

  // Load section data
  switch (section) {
    case 'dashboard': loadDashboard(); break;
    case 'users': loadUsers(1); break;
    case 'personas': loadPersonas(); break;
    case 'rankings': /* manual load */ break;
    case 'analytics': loadAnalytics(); break;
    case 'devices': loadDevices(); break;
    case 'notifications': loadTemplates(); break;
    case 'backup': loadBackups(); break;
    case 'audit': /* manual load */ break;
  }
}

// ── Clock ────────────────────────────────────────────────────
function updateClock() {
  const el = document.getElementById('topbar-time');
  if (el) el.textContent = new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

// ── Toast ────────────────────────────────────────────────────
function toast(msg, type = 'info') {
  const c = document.getElementById('toast-container');
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  const icons = { success: '✅', error: '❌', info: 'ℹ️' };
  t.innerHTML = `<span>${icons[type] || ''}</span><span>${DOMPurify.sanitize(String(msg))}</span>`;
  c.appendChild(t);
  setTimeout(() => t.remove(), 4000);
}

// ── Chart helper ─────────────────────────────────────────────
function destroyChart(id) {
  if (_charts[id]) { _charts[id].destroy(); delete _charts[id]; }
}

function createLineChart(id, labels, datasets, opts = {}) {
  destroyChart(id);
  const ctx = document.getElementById(id)?.getContext('2d');
  if (!ctx) return;
  _charts[id] = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      plugins: { legend: { labels: { color: '#94a3b8', font: { size: 12 } } } },
      scales: {
        x: { ticks: { color: '#6b7280' }, grid: { color: 'rgba(255,255,255,0.05)' } },
        y: { ticks: { color: '#6b7280' }, grid: { color: 'rgba(255,255,255,0.05)' } },
      },
      ...opts,
    },
  });
}

function createBarChart(id, labels, datasets, opts = {}) {
  destroyChart(id);
  const ctx = document.getElementById(id)?.getContext('2d');
  if (!ctx) return;
  _charts[id] = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets },
    options: {
      responsive: true,
      plugins: { legend: { labels: { color: '#94a3b8', font: { size: 12 } } } },
      scales: {
        x: { ticks: { color: '#6b7280' }, grid: { color: 'rgba(255,255,255,0.04)' } },
        y: { ticks: { color: '#6b7280' }, grid: { color: 'rgba(255,255,255,0.04)' } },
      },
      ...opts,
    },
  });
}

function createDonutChart(id, labels, data, colors) {
  destroyChart(id);
  const ctx = document.getElementById(id)?.getContext('2d');
  if (!ctx) return;
  _charts[id] = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{ data, backgroundColor: colors, borderColor: '#111827', borderWidth: 2 }],
    },
    options: {
      responsive: true,
      cutout: '65%',
      plugins: {
        legend: { position: 'right', labels: { color: '#94a3b8', font: { size: 12 }, padding: 16 } },
      },
    },
  });
}

// ── Dashboard ─────────────────────────────────────────────────
async function loadDashboard() {
  try {
    const [dash, decisions, energy] = await Promise.all([
      api('/api/admin/dashboard'),
      api('/api/admin/analytics/decisions'),
      api('/api/admin/analytics/energy?days=7'),
    ]);

    if (dash) {
      document.getElementById('kpi-total-users').textContent = dash.total_users ?? '—';
      document.getElementById('kpi-active-users').textContent = `${dash.active_users_today} active today`;
      document.getElementById('kpi-total-homes').textContent = dash.total_homes ?? '—';
      document.getElementById('kpi-total-devices').textContent = `${dash.total_devices} devices`;
      document.getElementById('kpi-energy-kwh').textContent = `${(dash.energy_today_kwh || 0).toFixed(1)} kWh`;
      document.getElementById('kpi-cost-gbp').textContent = `£${(dash.cost_today_gbp || 0).toFixed(2)} cost`;
      document.getElementById('kpi-notif-count').textContent = dash.notifications_sent_today ?? '—';
      document.getElementById('kpi-decisions').textContent = `${dash.decisions_recorded_today} decisions`;
      document.getElementById('kpi-adherence-pct').textContent = `${(dash.avg_goal_adherence_pct || 0).toFixed(0)}%`;
    }

    if (decisions) {
      document.getElementById('di-total').textContent = decisions.total_decisions ?? '—';
      document.getElementById('di-saved-kwh').textContent = `${(decisions.total_energy_saved_kwh || 0).toFixed(1)} kWh`;
      document.getElementById('di-saved-gbp').textContent = `£${(decisions.total_cost_saved_gbp || 0).toFixed(2)}`;
      document.getElementById('di-effectiveness').textContent = decisions.avg_effectiveness_score ? `${decisions.avg_effectiveness_score.toFixed(0)}%` : '—%';
      document.getElementById('di-response-time').textContent = decisions.avg_response_time_seconds ? `${Math.round(decisions.avg_response_time_seconds)}s` : '—s';
    }

    if (energy?.length) {
      const labels = energy.map(r => r.date);
      createLineChart('chart-energy', labels, [
        {
          label: 'Total kWh',
          data: energy.map(r => r.total_kwh),
          borderColor: '#3b82f6',
          backgroundColor: 'rgba(59,130,246,0.1)',
          fill: true,
          tension: 0.4,
          pointRadius: 4,
        },
        {
          label: 'Cost £',
          data: energy.map(r => r.total_cost_gbp),
          borderColor: '#10b981',
          backgroundColor: 'rgba(16,185,129,0.08)',
          fill: true,
          tension: 0.4,
          pointRadius: 4,
          yAxisID: 'y2',
        },
      ], {
        scales: {
          x: { ticks: { color: '#6b7280' }, grid: { color: 'rgba(255,255,255,0.05)' } },
          y: { ticks: { color: '#6b7280', callback: v => `${v} kWh` }, grid: { color: 'rgba(255,255,255,0.05)' } },
          y2: { position: 'right', ticks: { color: '#10b981', callback: v => `£${v}` }, grid: { display: false } },
        },
      });
    }

    await loadPersonaDonut();
    await loadTopRankings();
  } catch (err) {
    console.error('Dashboard load error:', err);
    toast('Dashboard load failed: ' + err.message, 'error');
  }
}

async function loadPersonaDonut() {
  try {
    const personas = await api('/api/admin/personas');
    if (!personas?.length) return;
    const filtered = personas.filter(p => p.user_count > 0);
    createDonutChart(
      'chart-personas',
      filtered.map(p => p.name),
      filtered.map(p => p.user_count),
      filtered.map(p => _personaColors[p.name] || '#6b7280'),
    );
  } catch (err) { console.warn('Persona donut:', err.message); }
}

async function loadTopRankings() {
  const period = document.getElementById('ranking-period-select')?.value || 'DAILY';
  const el = document.getElementById('ranking-list');
  if (!el) return;
  try {
    const rows = await api(`/api/admin/rankings?period=${period}`);
    if (!rows?.length) { el.innerHTML = '<div class="loading-row">No ranking data yet</div>'; return; }
    el.innerHTML = rows.slice(0, 5).map(r => `
      <div class="ranking-entry">
        <div class="rank-badge rank-${r.rank <= 3 ? r.rank : 'n'}">${r.rank}</div>
        <div class="ranking-info">
          <div class="ranking-name">${DOMPurify.sanitize(r.home)}</div>
          <div class="ranking-score">Score: ${(r.score || 0).toFixed(0)} · ${DOMPurify.sanitize(r.user_name)}</div>
        </div>
        <div class="ranking-kwh">${(r.total_kwh || 0).toFixed(1)} kWh</div>
      </div>`).join('');
  } catch (err) { console.warn('Rankings:', err.message); }
}

// ── Users ─────────────────────────────────────────────────────
async function loadUsers(page = 1) {
  _currentPage.users = page;
  const search = document.getElementById('user-search')?.value || '';
  const personaId = document.getElementById('persona-filter')?.value || '';
  const tbody = document.getElementById('users-tbody');
  tbody.innerHTML = '<tr><td colspan="7" class="loading-row">Loading…</td></tr>';

  try {
    let url = `/api/admin/users?page=${page}&limit=20`;
    if (search) url += `&search=${encodeURIComponent(search)}`;
    if (personaId) url += `&persona_id=${personaId}`;
    const users = await api(url);

    if (!users?.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="loading-row">No users found</td></tr>';
      return;
    }

    tbody.innerHTML = users.map(u => {
      const pc = _personaBadgeClass[u.persona?.name] || 'diseng';
      return `
        <tr data-user-id="${u.id}">
          <td><input type="checkbox" class="user-checkbox" data-uid="${u.id}" ${_selectedUserIds.has(u.id) ? 'checked' : ''}/></td>
          <td>${DOMPurify.sanitize(u.name)}</td>
          <td>${DOMPurify.sanitize(u.email)}</td>
          <td>${u.persona_id ? `<span class="badge badge-${pc}">${DOMPurify.sanitize(u.persona?.name || 'Assigned')}</span>` : '<span class="badge badge-diseng">None</span>'}</td>
          <td>${u.last_login_at ? new Date(u.last_login_at).toLocaleDateString('en-GB') : '—'}</td>
          <td><span class="badge badge-${u.notifications_enabled ? 'enabled' : 'disabled'}">${u.notifications_enabled ? '✓ On' : '✗ Off'}</span></td>
          <td>
            <button class="btn-sm btn-outline" onclick="openUserPanel(${u.id})">Details</button>
            <button class="btn-sm btn-outline" onclick="toggleUserNotif(${u.id})">Toggle Notif</button>
          </td>
        </tr>`;
    }).join('');

    // Checkbox logic
    tbody.querySelectorAll('.user-checkbox').forEach(cb => {
      cb.addEventListener('change', e => {
        const uid = parseInt(e.target.dataset.uid);
        e.target.checked ? _selectedUserIds.add(uid) : _selectedUserIds.delete(uid);
        updateBulkBar();
      });
    });

  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" class="loading-row">Error: ${DOMPurify.sanitize(err.message)}</td></tr>`;
    toast('Users load failed', 'error');
  }
}

function updateBulkBar() {
  const bar = document.getElementById('bulk-bar');
  const count = document.getElementById('bulk-count');
  if (_selectedUserIds.size > 0) {
    bar.style.display = 'flex';
    count.textContent = `${_selectedUserIds.size} selected`;
  } else {
    bar.style.display = 'none';
  }
}

async function toggleUserNotif(userId) {
  try {
    const res = await api(`/api/admin/users/${userId}/toggle-notifications`, { method: 'PATCH' });
    toast(`Notifications ${res.notifications_enabled ? 'enabled' : 'disabled'} for user ${userId}`, 'success');
    loadUsers(_currentPage.users);
  } catch (err) { toast('Toggle failed: ' + err.message, 'error'); }
}

// ── User Detail Panel ─────────────────────────────────────────
async function openUserPanel(userId) {
  const overlay = document.getElementById('overlay');
  const panel = document.getElementById('user-panel');
  const body = document.getElementById('panel-body');
  overlay.style.display = 'block';
  panel.classList.add('open');
  body.innerHTML = '<div class="loading-row">Loading user details…</div>';

  try {
    const d = await api(`/api/admin/users/${userId}/details`);
    const u = d.user;
    const pc = _personaBadgeClass[u.persona] || 'diseng';

    body.innerHTML = `
      <div class="detail-section">
        <div class="detail-section-title">Profile</div>
        <div class="detail-row"><span class="detail-key">Name</span><span class="detail-val">${DOMPurify.sanitize(u.name)}</span></div>
        <div class="detail-row"><span class="detail-key">Email</span><span class="detail-val">${DOMPurify.sanitize(u.email)}</span></div>
        <div class="detail-row"><span class="detail-key">Joined</span><span class="detail-val">${new Date(u.created_at).toLocaleDateString('en-GB')}</span></div>
        <div class="detail-row"><span class="detail-key">Last Login</span><span class="detail-val">${u.last_login ? new Date(u.last_login).toLocaleString('en-GB') : '—'}</span></div>
        <div class="detail-row"><span class="detail-key">Push Token</span><span class="detail-val">${u.push_token_set ? '✅ Set' : '❌ Not set'}</span></div>
        <div class="detail-row"><span class="detail-key">Persona</span><span class="detail-val">${u.persona ? `<span class="badge badge-${pc}">${DOMPurify.sanitize(u.persona)}</span>` : '<span class="badge badge-diseng">Unclassified</span>'}</span></div>
        <div class="detail-row"><span class="detail-key">Notifications</span><span class="detail-val">${u.notifications_enabled ? '✅ Enabled' : '❌ Disabled'}</span></div>
      </div>

      <div class="detail-section">
        <div class="detail-section-title">Energy Goals</div>
        <div class="detail-row"><span class="detail-key">Daily Goal</span><span class="detail-val">${u.daily_goal_kwh ? `${u.daily_goal_kwh} kWh` : '—'}</span></div>
        <div class="detail-row"><span class="detail-key">Weekly Goal</span><span class="detail-val">${u.weekly_goal_kwh ? `${u.weekly_goal_kwh} kWh` : '—'}</span></div>
        <div class="detail-row"><span class="detail-key">Monthly Budget</span><span class="detail-val">${u.monthly_budget_gbp ? `£${u.monthly_budget_gbp}` : '—'}</span></div>
      </div>

      <div class="detail-section">
        <div class="detail-section-title">Decision Impact</div>
        <div class="detail-row"><span class="detail-key">Total Decisions</span><span class="detail-val">${d.decision_impact?.total_decisions ?? '—'}</span></div>
        <div class="detail-row"><span class="detail-key">Energy Saved</span><span class="detail-val" style="color:var(--success)">${d.decision_impact?.total_energy_saved_kwh ?? 0} kWh</span></div>
        <div class="detail-row"><span class="detail-key">Cost Saved</span><span class="detail-val" style="color:var(--success)">£${d.decision_impact?.total_cost_saved_gbp ?? 0}</span></div>
        <div class="detail-row"><span class="detail-key">Avg Effectiveness</span><span class="detail-val">${d.decision_impact?.avg_effectiveness_score ? `${d.decision_impact.avg_effectiveness_score}%` : '—'}</span></div>
      </div>

      <div class="detail-section">
        <div class="detail-section-title">Homes</div>
        ${d.homes?.map(h => `<div class="detail-row"><span class="detail-key">${DOMPurify.sanitize(h.name)}</span><span class="detail-val">${h.home_type} · ${h.num_occupants} occupant(s)</span></div>`).join('') || '<div class="detail-row"><span class="detail-key">No homes registered</span></div>'}
      </div>

      <div class="detail-section">
        <div class="detail-section-title">Actions</div>
        <div class="detail-actions">
          <button class="btn-sm btn-outline" onclick="toggleUserNotif(${u.id}); closeUserPanel();">Toggle Notifs</button>
          <button class="btn-sm btn-outline" onclick="adminResetPassword(${u.id})">Reset Password</button>
          <button class="btn-sm btn-outline" onclick="sendUserNotif(${u.id})">Send Notification</button>
        </div>
      </div>`;

    document.getElementById('panel-user-name').textContent = u.name;
  } catch (err) {
    body.innerHTML = `<div class="loading-row">Error: ${DOMPurify.sanitize(err.message)}</div>`;
  }
}

function closeUserPanel() {
  document.getElementById('overlay').style.display = 'none';
  document.getElementById('user-panel').classList.remove('open');
}

async function adminResetPassword(userId) {
  if (!confirm('Reset this user\'s password? A temporary password will be generated.')) return;
  try {
    const res = await api(`/api/admin/users/${userId}/reset-password`, { method: 'POST' });
    alert(`Temporary Password: ${res.temp_password}\n\nShare this securely. The user must change it on next login.`);
    toast('Password reset successful', 'success');
  } catch (err) { toast('Reset failed: ' + err.message, 'error'); }
}

async function sendUserNotif(userId) {
  const title = prompt('Notification title:');
  if (!title) return;
  const msg = prompt('Message:');
  if (!msg) return;
  try {
    await api('/api/admin/notifications/send', {
      method: 'POST',
      body: JSON.stringify({ title, message: msg, notification_type: 'ADMIN_BROADCAST', severity: 'INFO', user_ids: [userId] }),
    });
    toast('Notification sent!', 'success');
  } catch (err) { toast('Send failed: ' + err.message, 'error'); }
}

// ── Personas ─────────────────────────────────────────────────
async function loadPersonas() {
  try {
    const personas = await api('/api/admin/personas');
    const grid = document.getElementById('persona-cards');
    if (!personas?.length) { grid.innerHTML = '<div class="loading-row">No personas yet</div>'; return; }

    grid.innerHTML = personas.map(p => `
      <div class="persona-card" data-persona="${DOMPurify.sanitize(p.name)}" onclick="filterUsersByPersona(${p.id})">
        <div class="persona-name">${DOMPurify.sanitize(p.name)}</div>
        <div class="persona-label">USERS</div>
        <div class="persona-count" style="color:${_personaColors[p.name] || '#6b7280'}">${p.user_count}</div>
        <div class="persona-desc">${DOMPurify.sanitize(p.description || '')}</div>
      </div>`).join('');

    // Update persona filter dropdown
    const filter = document.getElementById('persona-filter');
    if (filter) {
      filter.innerHTML = '<option value="">All Personas</option>' +
        personas.map(p => `<option value="${p.id}">${DOMPurify.sanitize(p.name)}</option>`).join('');
    }

    // Persona comparison chart
    await loadPersonaComparisonChart();
  } catch (err) { toast('Personas load failed: ' + err.message, 'error'); }
}

async function loadPersonaComparisonChart() {
  const days = document.getElementById('persona-comparison-days')?.value || 30;
  try {
    const data = await api(`/api/admin/analytics/persona-comparison?days=${days}`);
    if (!data?.length) return;

    const labels = data.map(r => r.persona);
    createBarChart('chart-persona-compare', labels, [
      { label: 'Efficiency Score', data: data.map(r => r.avg_efficiency_score), backgroundColor: 'rgba(59,130,246,0.7)' },
      { label: 'Goal Adherence', data: data.map(r => r.avg_goal_adherence), backgroundColor: 'rgba(16,185,129,0.7)' },
      { label: 'Decision Score', data: data.map(r => r.avg_decision_score), backgroundColor: 'rgba(139,92,246,0.7)' },
    ], {
      scales: {
        x: { ticks: { color: '#6b7280' }, grid: { color: 'rgba(255,255,255,0.04)' } },
        y: { ticks: { color: '#6b7280', callback: v => `${v}%` }, grid: { color: 'rgba(255,255,255,0.04)' }, max: 100 },
      },
    });
  } catch (err) { console.warn('Persona comparison chart:', err.message); }
}

function filterUsersByPersona(personaId) {
  navigateTo('users');
  setTimeout(() => {
    document.getElementById('persona-filter').value = personaId;
    loadUsers(1);
  }, 100);
}

// ── Analytics ─────────────────────────────────────────────────
async function loadAnalytics(startDate, endDate) {
  const start = startDate || document.getElementById('analytics-start')?.value;
  const end = endDate || document.getElementById('analytics-end')?.value;

  let url = '/api/admin/analytics/energy?days=30';
  if (start && end) url = `/api/admin/analytics/energy?start_date=${start}&end_date=${end}`;

  try {
    const [energy, interactions] = await Promise.all([
      api(url),
      api(`/api/admin/analytics/user-interactions?days=${document.getElementById('interaction-days')?.value || 7}`),
    ]);

    if (energy?.length) {
      const labels = energy.map(r => r.date);
      createLineChart('chart-analytics-energy', labels, [
        { label: 'Total kWh', data: energy.map(r => r.total_kwh), borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.08)', fill: true, tension: 0.4 },
        { label: 'Total £', data: energy.map(r => r.total_cost_gbp), borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,0.08)', fill: true, tension: 0.4, yAxisID: 'y2' },
      ], {
        scales: {
          x: { ticks: { color: '#6b7280' }, grid: { color: 'rgba(255,255,255,0.05)' } },
          y: { ticks: { color: '#6b7280' }, grid: { color: 'rgba(255,255,255,0.05)' } },
          y2: { position: 'right', ticks: { color: '#10b981', callback: v => `£${v}` }, grid: { display: false } },
        },
      });
      createBarChart('chart-analytics-homes', labels, [
        { label: 'Active Homes', data: energy.map(r => r.active_homes), backgroundColor: 'rgba(139,92,246,0.7)', borderRadius: 4 },
      ]);
    }

    if (interactions?.length) {
      createBarChart('chart-interactions', interactions.map(r => r.interaction_type), [
        { label: 'Total Events', data: interactions.map(r => r.count), backgroundColor: 'rgba(59,130,246,0.7)', borderRadius: 4 },
        { label: 'Unique Users', data: interactions.map(r => r.unique_users), backgroundColor: 'rgba(16,185,129,0.7)', borderRadius: 4 },
      ], {
        indexAxis: 'y',
        scales: {
          x: { ticks: { color: '#6b7280' }, grid: { color: 'rgba(255,255,255,0.04)' } },
          y: { ticks: { color: '#94a3b8', font: { size: 11 } }, grid: { display: false } },
        },
      });
    }

    // Export CSV
    document.getElementById('btn-analytics-export').onclick = () => exportCsv(energy);

  } catch (err) { toast('Analytics load failed: ' + err.message, 'error'); }
}

function exportCsv(data) {
  if (!data?.length) return;
  const keys = Object.keys(data[0]);
  const csv = [keys.join(','), ...data.map(r => keys.map(k => r[k]).join(','))].join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `wattwise-analytics-${new Date().toISOString().slice(0,10)}.csv`;
  a.click();
}

// ── Devices ───────────────────────────────────────────────────
async function loadDevices() {
  const tbody = document.getElementById('devices-tbody');
  tbody.innerHTML = '<tr><td colspan="7" class="loading-row">Loading…</td></tr>';
  try {
    const devices = await api('/api/admin/devices/status');
    if (!devices?.length) { tbody.innerHTML = '<tr><td colspan="7" class="loading-row">No devices registered</td></tr>'; return; }

    const online = devices.filter(d => d.online).length;
    document.getElementById('device-status-summary').innerHTML = `
      <div class="device-stat"><strong>${devices.length}</strong> total devices</div>
      <div class="device-stat" style="color:var(--success)"><strong>${online}</strong> online (last 5 min)</div>
      <div class="device-stat" style="color:var(--danger)"><strong>${devices.length - online}</strong> offline</div>`;

    tbody.innerHTML = devices.map(d => `
      <tr>
        <td><span class="badge badge-${d.online ? 'online' : 'offline'}">${d.online ? '● Online' : '○ Offline'}</span></td>
        <td>${DOMPurify.sanitize(d.device_name)}</td>
        <td>${DOMPurify.sanitize(d.home)}</td>
        <td>${DOMPurify.sanitize(d.user)}</td>
        <td><code style="font-size:11px;color:#94a3b8">${DOMPurify.sanitize(d.entity_id || '—')}</code></td>
        <td>${d.last_seen ? new Date(d.last_seen).toLocaleString('en-GB') : '—'}</td>
        <td>${d.last_power_watts != null ? `${d.last_power_watts.toFixed(1)} W` : '—'}</td>
      </tr>`).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" class="loading-row">Error: ${DOMPurify.sanitize(err.message)}</td></tr>`;
    toast('Device status load failed', 'error');
  }
}

// ── Notifications ─────────────────────────────────────────────
async function loadTemplates() {
  const el = document.getElementById('template-list');
  el.innerHTML = '<div class="loading-row">Loading…</div>';
  try {
    const templates = await api('/api/admin/notifications/templates');
    if (!templates?.length) { el.innerHTML = '<div class="loading-row">No templates yet</div>'; return; }
    el.innerHTML = templates.map(t => `
      <div class="template-item" onclick="applyTemplate(${JSON.stringify(t).replace(/"/g, '&quot;')})">
        <div class="template-item-title">${DOMPurify.sanitize(t.name)}</div>
        <div class="template-item-type">${t.notification_type} · ${t.severity}</div>
      </div>`).join('');
  } catch (err) { el.innerHTML = `<div class="loading-row">Error loading templates</div>`; }
}

function applyTemplate(t) {
  const title = document.getElementById('notif-title');
  const msg = document.getElementById('notif-message');
  const type = document.getElementById('notif-type');
  const sev = document.getElementById('notif-severity');
  if (title) title.value = t.title_template || '';
  if (msg) msg.value = t.message_template || '';
  if (type) type.value = t.notification_type || 'ADMIN_BROADCAST';
  if (sev) sev.value = t.severity || 'INFO';
  toast('Template applied', 'info');
}

// ── Backups ───────────────────────────────────────────────────
async function loadBackups() {
  const el = document.getElementById('backup-list');
  el.innerHTML = '<div class="loading-row">Loading…</div>';
  try {
    const data = await api('/api/backup/list');
    const backups = data?.backups || [];
    if (!backups.length) { el.innerHTML = '<div class="loading-row">No backups yet</div>'; return; }
    el.innerHTML = backups.map(b => `
      <div class="backup-entry">
        <div class="backup-icon">💾</div>
        <div class="backup-info">
          <div class="backup-filename">${DOMPurify.sanitize(b.filename)}</div>
          <div class="backup-meta">${b.size_human || ''} · ${b.created_at ? new Date(b.created_at).toLocaleString('en-GB') : ''}</div>
        </div>
        <a href="/api/backup/download/${encodeURIComponent(b.filename)}" class="btn-outline btn-sm">⬇ Download</a>
      </div>`).join('');
  } catch (err) { el.innerHTML = `<div class="loading-row">Error loading backups</div>`; }
}

// ── Audit Log ─────────────────────────────────────────────────
async function loadAuditLog() {
  const tbody = document.getElementById('audit-tbody');
  tbody.innerHTML = '<tr><td colspan="6" class="loading-row">Loading…</td></tr>';
  const days = document.getElementById('audit-days')?.value || 30;
  const actionType = document.getElementById('audit-action-filter')?.value || '';

  try {
    let url = `/api/admin/audit-log?days=${days}&limit=100`;
    if (actionType) url += `&action_type=${actionType}`;
    const logs = await api(url);
    if (!logs?.length) { tbody.innerHTML = '<tr><td colspan="6" class="loading-row">No audit entries found</td></tr>'; return; }

    tbody.innerHTML = logs.map(l => `
      <tr>
        <td>${new Date(l.created_at).toLocaleString('en-GB')}</td>
        <td>${l.admin_user_id || '—'}</td>
        <td><code style="font-size:11px;color:#60a5fa">${DOMPurify.sanitize(l.action_type)}</code></td>
        <td>${l.target_user_id || '—'}</td>
        <td><span style="font-size:11px;color:#94a3b8">${l.details ? JSON.stringify(l.details).slice(0,80) : '—'}</span></td>
        <td>${DOMPurify.sanitize(l.ip_address || '—')}</td>
      </tr>`).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="loading-row">Error loading audit log</td></tr>`;
  }
}

// ── Rankings ──────────────────────────────────────────────────
async function loadRankings() {
  const period = document.getElementById('rankings-period')?.value || 'DAILY';
  const dateInput = document.getElementById('rankings-date')?.value;
  const tbody = document.getElementById('rankings-tbody');
  tbody.innerHTML = '<tr><td colspan="9" class="loading-row">Loading…</td></tr>';

  try {
    let url = `/api/admin/rankings?period=${period}`;
    if (dateInput) url += `&date_str=${dateInput}`;
    const rows = await api(url);
    if (!rows?.length) { tbody.innerHTML = '<tr><td colspan="9" class="loading-row">No data for selected period</td></tr>'; return; }

    tbody.innerHTML = rows.map(r => `
      <tr>
        <td><strong>#${r.rank}</strong></td>
        <td>${DOMPurify.sanitize(r.home)}</td>
        <td>${DOMPurify.sanitize(r.user_name)}</td>
        <td><strong style="color:var(--brand)">${(r.score || 0).toFixed(1)}</strong></td>
        <td>${(r.efficiency || 0).toFixed(0)}%</td>
        <td>${(r.goal_adherence || 0).toFixed(0)}%</td>
        <td>${(r.total_kwh || 0).toFixed(2)}</td>
        <td>£${(r.cost_gbp || 0).toFixed(2)}</td>
        <td>${r.percentile ? `${r.percentile.toFixed(0)}th` : '—'}</td>
      </tr>`).join('');
  } catch (err) { toast('Rankings load failed: ' + err.message, 'error'); }
}

// ── Initialisation ────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', async () => {
  if (!await checkAuth()) return;

  // Navigation
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', e => {
      e.preventDefault();
      navigateTo(item.dataset.section);
    });
  });

  // Sidebar toggle
  document.getElementById('btn-sidebar-toggle').addEventListener('click', () => {
    document.getElementById('sidebar').classList.toggle('collapsed');
    document.querySelector('.main-content').classList.toggle('expanded');
  });

  // Logout
  document.getElementById('btn-logout').addEventListener('click', doLogout);

  // Clock
  updateClock(); setInterval(updateClock, 1000);

  // Close panel
  document.getElementById('overlay').addEventListener('click', closeUserPanel);
  document.getElementById('btn-close-panel').addEventListener('click', closeUserPanel);

  // Bulk operations
  document.getElementById('btn-bulk-op').addEventListener('click', () => {
    document.getElementById('bulk-bar').style.display =
      document.getElementById('bulk-bar').style.display === 'none' ? 'flex' : 'none';
  });
  document.getElementById('bulk-cancel').addEventListener('click', () => {
    _selectedUserIds.clear();
    document.querySelectorAll('.user-checkbox').forEach(cb => cb.checked = false);
    updateBulkBar();
  });
  document.getElementById('bulk-enable-notif').addEventListener('click', async () => {
    if (!_selectedUserIds.size) return;
    try {
      const ids = [..._selectedUserIds].join('&user_ids=');
      await api(`/api/admin/users/bulk-operation?operation=enable_notifications&user_ids=${ids}`, { method: 'POST' });
      toast(`Enabled notifications for ${_selectedUserIds.size} users`, 'success');
      _selectedUserIds.clear(); loadUsers(_currentPage.users);
    } catch (err) { toast('Bulk op failed: ' + err.message, 'error'); }
  });
  document.getElementById('bulk-disable-notif').addEventListener('click', async () => {
    if (!_selectedUserIds.size) return;
    try {
      const ids = [..._selectedUserIds].join('&user_ids=');
      await api(`/api/admin/users/bulk-operation?operation=disable_notifications&user_ids=${ids}`, { method: 'POST' });
      toast(`Disabled notifications for ${_selectedUserIds.size} users`, 'success');
      _selectedUserIds.clear(); loadUsers(_currentPage.users);
    } catch (err) { toast('Bulk op failed: ' + err.message, 'error'); }
  });
  document.getElementById('bulk-send-notif').addEventListener('click', () => {
    if (!_selectedUserIds.size) return;
    document.getElementById('modal-backdrop').style.display = 'flex';
  });
  document.getElementById('btn-close-modal').addEventListener('click', () => {
    document.getElementById('modal-backdrop').style.display = 'none';
  });
  document.getElementById('btn-modal-cancel').addEventListener('click', () => {
    document.getElementById('modal-backdrop').style.display = 'none';
  });
  document.getElementById('btn-modal-send').addEventListener('click', async () => {
    const title = document.getElementById('modal-notif-title').value;
    const msg = document.getElementById('modal-notif-message').value;
    if (!title || !msg) { toast('Fill in title and message', 'error'); return; }
    try {
      const ids = [..._selectedUserIds].join('&user_ids=');
      await api(`/api/admin/users/bulk-operation?operation=send_notification&notification_title=${encodeURIComponent(title)}&notification_message=${encodeURIComponent(msg)}&user_ids=${ids}`, { method: 'POST' });
      toast(`Notification sent to ${_selectedUserIds.size} users`, 'success');
      document.getElementById('modal-backdrop').style.display = 'none';
      _selectedUserIds.clear(); updateBulkBar();
    } catch (err) { toast('Send failed: ' + err.message, 'error'); }
  });

  // User search
  let searchTimer;
  document.getElementById('user-search').addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadUsers(1), 400);
  });
  document.getElementById('persona-filter').addEventListener('change', () => loadUsers(1));

  // Persona classifier
  document.getElementById('btn-run-classifier').addEventListener('click', async () => {
    try {
      toast('Running persona classification…', 'info');
      const res = await api('/api/admin/personas/run-classifier', { method: 'POST' });
      toast('Classification complete: ' + JSON.stringify(res.classification_summary), 'success');
      loadPersonas();
    } catch (err) { toast('Classifier failed: ' + err.message, 'error'); }
  });

  // Analytics controls
  document.getElementById('btn-analytics-load').addEventListener('click', () => {
    const s = document.getElementById('analytics-start').value;
    const e = document.getElementById('analytics-end').value;
    loadAnalytics(s, e);
  });
  document.querySelectorAll('.btn-chip[data-days]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.btn-chip').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const days = parseInt(btn.dataset.days);
      const end = new Date().toISOString().slice(0,10);
      const start = new Date(Date.now() - days * 86400000).toISOString().slice(0,10);
      document.getElementById('analytics-start').value = start;
      document.getElementById('analytics-end').value = end;
      loadAnalytics(start, end);
    });
  });
  document.getElementById('btn-load-interactions').addEventListener('click', loadAnalytics);
  document.getElementById('persona-comparison-days').addEventListener('change', loadPersonaComparisonChart);

  // Rankings
  document.getElementById('btn-load-rankings').addEventListener('click', loadRankings);
  document.getElementById('ranking-period-select').addEventListener('change', loadTopRankings);

  // Devices
  document.getElementById('btn-refresh-devices').addEventListener('click', loadDevices);

  // Notifications form
  document.getElementById('notif-form').addEventListener('submit', async e => {
    e.preventDefault();
    const feedback = document.getElementById('notif-feedback');
    feedback.textContent = 'Sending…';
    feedback.className = 'form-feedback';
    try {
      const target = document.getElementById('notif-target').value;
      const userIdsStr = document.getElementById('notif-user-ids')?.value || '';
      const userIds = target === 'specific' ? userIdsStr.split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n)) : null;

      const res = await api('/api/admin/notifications/send', {
        method: 'POST',
        body: JSON.stringify({
          title: document.getElementById('notif-title').value,
          message: document.getElementById('notif-message').value,
          notification_type: document.getElementById('notif-type').value,
          severity: document.getElementById('notif-severity').value,
          user_ids: userIds,
        }),
      });
      feedback.textContent = `✅ Sent to ${res.notifications_sent} users`;
      feedback.className = 'form-feedback success';
    } catch (err) {
      feedback.textContent = `❌ ${err.message}`;
      feedback.className = 'form-feedback error';
    }
  });
  document.getElementById('notif-target').addEventListener('change', e => {
    const extra = document.getElementById('notif-target-extra');
    extra.style.display = e.target.value === 'specific' ? 'block' : 'none';
  });
  document.getElementById('btn-refresh-templates').addEventListener('click', loadTemplates);

  // Backup
  document.getElementById('btn-trigger-backup').addEventListener('click', async () => {
    try {
      toast('Creating backup…', 'info');
      await api('/api/backup/create', { method: 'POST' });
      toast('Backup created!', 'success');
      loadBackups();
    } catch (err) { toast('Backup failed: ' + err.message, 'error'); }
  });
  document.getElementById('btn-trigger-agg').addEventListener('click', async () => {
    const days = document.getElementById('agg-days').value;
    const feedback = document.getElementById('agg-feedback');
    feedback.textContent = `Running aggregation for ${days} days…`;
    feedback.className = 'form-feedback';
    try {
      const res = await api(`/api/admin/trigger-aggregations?days=${days}`, { method: 'POST' });
      feedback.textContent = `✅ ${res.message}`;
      feedback.className = 'form-feedback success';
    } catch (err) {
      feedback.textContent = `❌ ${err.message}`;
      feedback.className = 'form-feedback error';
    }
  });

  // Audit
  document.getElementById('btn-load-audit').addEventListener('click', loadAuditLog);

  // Set default analytics dates
  const today = new Date().toISOString().slice(0,10);
  const week = new Date(Date.now() - 7 * 86400000).toISOString().slice(0,10);
  document.getElementById('analytics-start').value = week;
  document.getElementById('analytics-end').value = today;
  document.getElementById('rankings-date').value = new Date(Date.now() - 86400000).toISOString().slice(0,10);

  // Load initial section
  navigateTo('dashboard');

  // Expose to onclick handlers
  window.openUserPanel = openUserPanel;
  window.toggleUserNotif = toggleUserNotif;
  window.closeUserPanel = closeUserPanel;
  window.adminResetPassword = adminResetPassword;
  window.sendUserNotif = sendUserNotif;
  window.filterUsersByPersona = filterUsersByPersona;
  window.applyTemplate = applyTemplate;
});
