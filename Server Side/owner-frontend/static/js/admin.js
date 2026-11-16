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
          <button id="login-submit-btn" type="submit"
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
    const loginBtn = document.getElementById('login-submit-btn');
    errEl.textContent = '';
    if (loginBtn) { loginBtn.disabled = true; loginBtn.textContent = 'Signing in…'; }
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
    } catch (error) {
      console.error("Login failed:", error);
      sessionStorage.removeItem("ww_admin_token");
      errEl.textContent = error.message || "Login failed. Please check your credentials.";
    } finally {
      if (loginBtn) { loginBtn.disabled = false; loginBtn.textContent = "Sign In"; }
    }
  });
}

function doLogout() {
  api('/api/auth/logout', { method: 'POST' }).catch(() => {});
  sessionStorage.removeItem('ww_admin_token');
  location.reload();
}


// ── Cohort (real / synthetic / all) ───────────────────────────
// Real participants and synthetic demo accounts are never mixed unless "All" is chosen.
let _cohort = sessionStorage.getItem('ww_admin_cohort') || 'real';
const COHORT_LABELS = { real: 'real participants', synthetic: 'synthetic demo accounts', all: 'all accounts' };
function cohortQS(prefix = '&') { return `${prefix}cohort=${_cohort}`; }
function paintCohortLabels() {
  document.querySelectorAll('[data-cohort-label]').forEach(el => { el.textContent = `· ${COHORT_LABELS[_cohort]}`; });
  const sw = document.getElementById('cohort-switch');
  if (sw) sw.value = _cohort;
}

function h(v) {
  return String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function fmtWhen(iso) {
  if (!iso) return '—';
  return new Date(String(iso).endsWith('Z') ? iso : iso + 'Z').toLocaleString('en-GB', { dateStyle: 'short', timeStyle: 'short' });
}
function fmtDuration(s) {
  if (s == null) return '—';
  if (s < 90) return `${Math.round(s)} s`;
  if (s < 5400) return `${Math.round(s / 60)} min`;
  return `${(s / 3600).toFixed(1)} h`;
}
const DECISION_LABELS = { ACCEPTED: '✅ Done', CUSTOM_ACTION: '✍️ Own action', DEFERRED: '⏰ Later', REJECTED: '❌ Skipped' };

// ── Decisions section ─────────────────────────────────────────
function loadDecisionsSection() {
  paintCohortLabels();
  loadFunnel();
  loadCampaigns();
  loadDecisionExplorer(1);
}

async function loadFunnel() {
  const kpis = document.getElementById('funnel-kpis');
  const tbody = document.getElementById('funnel-tbody');
  try {
    const days = document.getElementById('funnel-days').value;
    const source = document.getElementById('funnel-source').value;
    const f = await api(`/api/admin/notifications/funnel?days=${days}${cohortQS()}${source ? '&source=' + source : ''}`);
    const o = f.overall;
    const stat = (v, l) => `<div class="impact-stat"><div class="impact-val">${v}</div><div class="impact-lbl">${l}</div></div>`;
    kpis.innerHTML =
      stat(o.sent, 'Alerts sent') + stat(o.opened, 'Opened') + stat(o.actionable, 'Asked for a response') +
      stat(o.decided, 'Responded') + stat(o.no_response, 'No response') +
      stat(o.response_rate == null ? '—' : o.response_rate + '%', 'Response rate') +
      stat(o.measured, 'Impact measured') + stat((o.saved_kwh || 0).toFixed(2), 'kWh saved');
    tbody.innerHTML = f.by_type.length ? f.by_type.map(r => `<tr>
        <td>${h(r.notification_type)}</td><td>${r.source === 'ADMIN' ? 'Admin' : 'Automated'}</td>
        <td>${r.sent}</td><td>${r.opened}</td><td>${r.actionable}</td><td>${r.decided}</td>
        <td>${r.accepted + r.custom_action}</td><td>${r.deferred}</td><td>${r.rejected}</td>
        <td>${r.response_rate == null ? '—' : r.response_rate + '%'}</td>
        <td>${fmtDuration(r.avg_response_time_seconds)}</td><td>${(r.saved_kwh || 0).toFixed(2)}</td></tr>`).join('')
      : '<tr><td colspan="12" class="loading-row">No alerts in this period for this cohort</td></tr>';
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="12" class="loading-row">Error: ${h(err.message)}</td></tr>`;
  }
}

function describeTarget(t) {
  if (!t) return 'Everyone';
  if (t.user_ids?.length) return `${t.user_ids.length} user(s)`;
  if (t.home_ids?.length) return `${t.home_ids.length} home(s)`;
  const who = t.target_persona_id ? `persona #${t.target_persona_id}` : 'everyone';
  const cohort = t.cohort && t.cohort !== 'all' ? ` · ${t.cohort}` : '';
  return who + cohort + (t.appliance_key ? ` · ${t.appliance_key}` : '');
}

async function loadCampaigns() {
  const tbody = document.getElementById('campaigns-tbody');
  try {
    const res = await api(`/api/admin/campaigns?limit=50${cohortQS()}`);
    const list = res.campaigns || [];
    tbody.innerHTML = list.length ? list.map(c => {
      const f = c.funnel || {};
      const when = c.status === 'SCHEDULED' ? 'Scheduled ' + fmtWhen(c.send_at) : fmtWhen(c.sent_at || c.created_at);
      return `<tr class="row-click" data-campaign="${c.id}">
        <td>${when}</td><td>${h(c.title)}${c.requires_user_action ? ' <span class="tag-sim">asks for response</span>' : ''}</td>
        <td>${h(describeTarget(c.target))}</td><td>${h(c.status)}</td>
        <td>${c.notifications_created}</td><td>${f.opened ?? '—'}</td><td>${f.decided ?? '—'}</td><td>${f.no_response ?? '—'}</td>
        <td>${f.response_rate == null ? '—' : f.response_rate + '%'}</td>
        <td>${c.status === 'SCHEDULED' ? `<button class="btn-sm btn-outline" data-cancel-campaign="${c.id}">Cancel</button>` : '<span style="color:#9ca3af">View ▸</span>'}</td></tr>`;
    }).join('') : '<tr><td colspan="10" class="loading-row">No admin sends yet — use the Notifications tab</td></tr>';
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="10" class="loading-row">Error: ${h(err.message)}</td></tr>`;
  }
}

async function showCampaign(id) {
  const box = document.getElementById('campaign-detail');
  box.style.display = 'block';
  box.innerHTML = '<div class="loading-row">Loading recipients…</div>';
  try {
    const d = await api(`/api/admin/campaigns/${id}?cohort=${_cohort}`);
    const c = d.campaign, sc = d.status_counts;
    const rows = d.recipients.map(r => {
      const dec = r.decision;
      return `<tr>
        <td>${h(r.user_name)}${r.is_synthetic ? ' <span class="tag-sim">synthetic</span>' : ''}<div class="dx-note">${h(r.user_email)}</div></td>
        <td>${h(r.status)}</td><td>${fmtWhen(r.opened_at)}</td>
        <td>${dec ? (DECISION_LABELS[dec.decision_type] || h(dec.decision_type)) : '—'}${dec?.is_simulated ? ' <span class="tag-sim">simulated</span>' : ''}</td>
        <td>${dec?.action_taken ? h(dec.action_taken) : '—'}${dec?.user_feedback_text ? `<div class="dx-note">“${h(dec.user_feedback_text)}”</div>` : ''}</td>
        <td>${dec?.user_satisfaction ? '★'.repeat(dec.user_satisfaction) : '—'}</td>
        <td>${dec ? fmtDuration(dec.response_time_seconds) : '—'}</td>
        <td>${dec?.energy_saved_kwh != null ? Number(dec.energy_saved_kwh).toFixed(3) : '—'}</td></tr>`;
    }).join('');
    box.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap">
        <div><strong>${h(c.title)}</strong><div class="dx-note" style="max-width:none">${h(c.message)}</div></div>
        <div style="font-size:12px;color:#9ca3af">${sc.delivered} not seen · ${sc.seen} seen · ${sc.opened} opened · ${sc.decided} responded</div>
      </div>
      <div class="table-wrap"><table class="data-table">
        <thead><tr><th>Recipient</th><th>Status</th><th>Opened</th><th>Decision</th><th>What they did</th><th>Rating</th><th>Response time</th><th>kWh saved</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="8" class="loading-row">No recipients in this cohort</td></tr>'}</tbody></table></div>`;
    box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  } catch (err) { box.innerHTML = `<div class="loading-row">Error: ${h(err.message)}</div>`; }
}

function decisionFilterQS() {
  const v = id => document.getElementById(id).value;
  let qs = `cohort=${_cohort}`;
  if (v('dx-type')) qs += `&decision_type=${v('dx-type')}`;
  if (v('dx-source')) qs += `&source=${v('dx-source')}`;
  if (v('dx-measured') !== 'any') qs += `&measured=${v('dx-measured')}`;
  if (v('dx-from')) qs += `&date_from=${v('dx-from')}`;
  if (v('dx-to')) qs += `&date_to=${v('dx-to')}`;
  if (v('dx-user')) qs += `&user_id=${parseInt(v('dx-user'), 10)}`;
  return qs;
}

async function loadDecisionExplorer(page = 1) {
  const tbody = document.getElementById('dx-tbody');
  const pager = document.getElementById('dx-pager');
  try {
    const limit = 25;
    const res = await api(`/api/admin/decisions?${decisionFilterQS()}&page=${page}&limit=${limit}`);
    tbody.innerHTML = res.items.length ? res.items.map(r => `<tr>
        <td>${fmtWhen(r.decided_at)}</td>
        <td>${h(r.user_name)}${r.is_synthetic ? ' <span class="tag-sim">synthetic</span>' : ''}<div class="dx-note">${h(r.persona || '')}</div></td>
        <td>${h(r.alert_title || '(alert removed)')}<div class="dx-note">${h(r.alert_type || '')}${r.alert_source === 'ADMIN' ? ' · admin send' : ''}${r.alert_opened_at ? ' · opened ' + fmtWhen(r.alert_opened_at) : ''}</div></td>
        <td>${h(r.device_name || (r.impact_scope === 'home' ? 'Whole home' : '—'))}</td>
        <td>${DECISION_LABELS[r.decision_type] || h(r.decision_type)}${r.is_simulated ? ' <span class="tag-sim">simulated</span>' : ''}</td>
        <td>${r.action_taken ? h(r.action_taken) : '—'}${r.user_feedback_text ? `<div class="dx-note">“${h(r.user_feedback_text)}”</div>` : ''}</td>
        <td>${r.user_satisfaction ? '★'.repeat(r.user_satisfaction) : '—'}</td>
        <td>${fmtDuration(r.response_time_seconds)}</td>
        <td>${r.energy_saved_kwh != null ? Number(r.energy_saved_kwh).toFixed(3) : (r.impact_scope === 'none' ? 'n/a' : 'pending')}</td>
        <td>${r.effectiveness_score != null ? Math.round(r.effectiveness_score) + '%' : '—'}</td></tr>`).join('')
      : `<tr><td colspan="10" class="loading-row">No decisions match for ${COHORT_LABELS[_cohort]}</td></tr>`;
    const pages = Math.max(1, Math.ceil(res.total / limit));
    pager.innerHTML = `<span>${res.total} decision(s)</span>
      <button class="btn-sm btn-outline" data-dx-page="${page - 1}" ${page <= 1 ? 'disabled' : ''}>‹ Prev</button>
      <span>Page ${page} of ${pages}</span>
      <button class="btn-sm btn-outline" data-dx-page="${page + 1}" ${page >= pages ? 'disabled' : ''}>Next ›</button>`;
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="10" class="loading-row">Error: ${h(err.message)}</td></tr>`;
  }
}

async function exportDecisionsCsv() {
  try {
    const res = await fetch(`${API_BASE}/api/admin/decisions?${decisionFilterQS()}&format=csv`, { headers: { Authorization: `Bearer ${_token}` } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = (res.headers.get('Content-Disposition') || '').match(/filename="?([^"]+)"?/)?.[1] || 'wattwise-decisions.csv';
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(a.href);
    toast('Decisions exported', 'success');
  } catch (err) { toast('Export failed: ' + err.message, 'error'); }
}

function initDecisionsUi() {
  paintCohortLabels();
  document.getElementById('cohort-switch').addEventListener('change', e => {
    _cohort = e.target.value;
    sessionStorage.setItem('ww_admin_cohort', _cohort);
    paintCohortLabels();
    const active = document.querySelector('.section.active')?.id?.replace('section-', '') || 'dashboard';
    navigateTo(active);
  });
  document.getElementById('funnel-days').addEventListener('change', loadFunnel);
  document.getElementById('funnel-source').addEventListener('change', loadFunnel);
  document.getElementById('btn-reload-campaigns').addEventListener('click', loadCampaigns);
  document.getElementById('btn-dx-apply').addEventListener('click', () => loadDecisionExplorer(1));
  document.getElementById('btn-dx-export').addEventListener('click', exportDecisionsCsv);
  document.getElementById('dx-pager').addEventListener('click', e => {
    const b = e.target.closest('[data-dx-page]');
    if (b && !b.disabled) loadDecisionExplorer(parseInt(b.dataset.dxPage, 10));
  });
  document.getElementById('campaigns-tbody').addEventListener('click', async e => {
    const cancel = e.target.closest('[data-cancel-campaign]');
    if (cancel) {
      e.stopPropagation();
      try { await api(`/api/admin/campaigns/${cancel.dataset.cancelCampaign}/cancel`, { method: 'POST' }); toast('Scheduled send cancelled', 'success'); loadCampaigns(); }
      catch (err) { toast('Cancel failed: ' + err.message, 'error'); }
      return;
    }
    const row = e.target.closest('[data-campaign]');
    if (row) showCampaign(parseInt(row.dataset.campaign, 10));
  });
  document.getElementById('notif-requires-action').addEventListener('change', e => {
    document.getElementById('notif-action-fields').style.display = e.target.checked ? 'block' : 'none';
  });
  document.getElementById('btn-notif-save-template').addEventListener('click', saveNotifTemplate);
  // Users table actions (delegated — no user-supplied text is ever placed inside a JS handler)
  document.getElementById('users-tbody').addEventListener('click', e => {
    const btn = e.target.closest('[data-user-act]');
    if (!btn) return;
    const uid = parseInt(btn.dataset.uid, 10);
    if (btn.dataset.userAct === 'details') openUserPanel(uid);
    else if (btn.dataset.userAct === 'toggle') toggleUserNotif(uid);
    else if (btn.dataset.userAct === 'drill') toggleUserDrill(uid, btn.dataset.name || '', btn);
  });
}

async function saveNotifTemplate() {
  const title = document.getElementById('notif-title').value.trim();
  const message = document.getElementById('notif-message').value.trim();
  if (!title || !message) { toast('Fill in the title and message first', 'error'); return; }
  const name = prompt('Template name:', title.slice(0, 60));
  if (!name) return;
  try {
    await api('/api/admin/notifications/templates', { method: 'POST', body: JSON.stringify({
      name, title_template: title, message_template: message,
      notification_type: document.getElementById('notif-type').value,
      severity: document.getElementById('notif-severity').value,
      requires_user_action: document.getElementById('notif-requires-action').checked,
      action_hint: document.getElementById('notif-action-hint').value.trim() || null,
      action_button_text: document.getElementById('notif-button-text').value.trim() || null,
    }) });
    toast('Template saved', 'success');
    loadTemplates();
  } catch (err) { toast('Could not save template: ' + err.message, 'error'); }
}


// ── Homes (which households report; onboarding a new one) ──────
const APPLIANCE_OPTIONS = [
  ['kettle', 'Kettle'], ['microwave', 'Microwave'], ['washing_machine', 'Washing machine'], ['dishwasher', 'Dishwasher'],
  ['toaster', 'Toaster'], ['airfryer', 'Air fryer'], ['dryer', 'Dryer'], ['cooker', 'Cooker'], ['tv', 'TV'],
  ['coffeemachine', 'Coffee machine'], ['gaming_console', 'Games console'], ['water_purifier', 'Water purifier'],
];

async function loadHomes() {
  const tbody = document.getElementById('homes-tbody');
  paintCohortLabels();
  try {
    const res = await api(`/api/admin/homes/status?cohort=${_cohort}`);
    const s = res.summary;
    document.getElementById('homes-summary').textContent =
      `${s.rpi_homes} RPi home(s): ${s.rpi_online} online, ${s.rpi_offline} not reporting`;
    const badge = st => st === 'online' ? '<span class="badge badge-enabled">● Online</span>'
      : st === 'offline' ? '<span class="badge badge-disabled">● Offline</span>'
      : '<span class="badge badge-diseng">Never seen</span>';
    tbody.innerHTML = res.homes.length ? res.homes.map(hm => `<tr>
        <td>${badge(hm.state)}</td>
        <td>${h(hm.home_name)} <span style="color:#9ca3af">#${hm.home_id}</span></td>
        <td>${h(hm.user_name)}${hm.is_synthetic ? ' <span class="tag-sim">synthetic</span>' : ''}<div class="dx-note">${h(hm.user_email)}</div></td>
        <td>${hm.feed === 'rpi' ? 'Raspberry Pi' : hm.feed === 'generator' ? 'Data generator' : '—'}</td>
        <td>${hm.mqtt_username ? h(hm.mqtt_username) + (hm.managed ? '' : ' <span class="tag-sim">legacy</span>') : '—'}</td>
        <td>${hm.devices_reporting} / ${hm.devices}</td>
        <td>${hm.last_seen_at ? fmtWhen(hm.last_seen_at) + `<div class="dx-note">${fmtDuration(hm.minutes_since_seen * 60)} ago</div>` : '—'}</td>
        <td>${hm.publisher_status ? h(hm.publisher_status) : '—'}</td>
        <td>${hm.mqtt_username ? `<button class="btn-sm btn-outline" data-home-act="config" data-home="${hm.home_id}">Config</button>` : ''}
            ${hm.managed ? `<button class="btn-sm btn-outline" data-home-act="rotate" data-home="${hm.home_id}" data-name="${h(hm.mqtt_username)}">New password</button>` : ''}</td>
      </tr>`).join('') : `<tr><td colspan="9" class="loading-row">No homes for ${COHORT_LABELS[_cohort]}</td></tr>`;
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="9" class="loading-row">Error: ${h(err.message)}</td></tr>`;
  }
}

function addHomeDeviceRow(appliance = 'kettle') {
  const row = document.createElement('div');
  row.className = 'hf-device';
  row.style.cssText = 'display:flex;gap:8px;flex-wrap:wrap;margin-bottom:6px;align-items:center';
  row.innerHTML = `
    <select class="input-field hf-appliance" style="width:170px">${APPLIANCE_OPTIONS.map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}</select>
    <input type="text" class="input-field hf-dname" style="flex:1;min-width:150px" maxlength="128" placeholder="Name shown to the participant"/>
    <input type="text" class="input-field hf-tag" style="flex:1;min-width:210px" maxlength="128" placeholder="Pi's InfluxDB tag (optional)"/>
    <button type="button" class="btn-sm btn-outline hf-remove" title="Remove">✕</button>`;
  row.querySelector('.hf-appliance').value = appliance;
  const sync = () => {
    const name = row.querySelector('.hf-dname');
    if (!name.dataset.touched) name.value = row.querySelector('.hf-appliance').selectedOptions[0].textContent;
  };
  row.querySelector('.hf-appliance').addEventListener('change', sync);
  row.querySelector('.hf-dname').addEventListener('input', e => { e.target.dataset.touched = '1'; });
  row.querySelector('.hf-remove').addEventListener('click', () => row.remove());
  sync();
  document.getElementById('hf-devices').appendChild(row);
}

function showHomeResult(headHtml, yaml, filename) {
  const box = document.getElementById('home-result');
  document.getElementById('home-result-head').innerHTML = headHtml;
  const ta = document.getElementById('home-result-yaml');
  ta.value = yaml;
  ta.dataset.filename = filename;
  box.style.display = 'block';
  box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

async function submitHomeForm(e) {
  e.preventDefault();
  const fb = document.getElementById('hf-feedback');
  const devices = Array.from(document.querySelectorAll('#hf-devices .hf-device')).map(r => ({
    appliance_key: r.querySelector('.hf-appliance').value,
    name: r.querySelector('.hf-dname').value.trim() || r.querySelector('.hf-appliance').selectedOptions[0].textContent,
    power_entity_id: r.querySelector('.hf-tag').value.trim() || null,
  }));
  if (!devices.length) { fb.textContent = '❌ Add at least one device'; fb.className = 'form-feedback error'; return; }
  const btn = document.getElementById('hf-submit');
  btn.disabled = true; fb.textContent = 'Creating…'; fb.className = 'form-feedback';
  try {
    const res = await api('/api/admin/homes/provision', { method: 'POST', body: JSON.stringify({
      participant_name: document.getElementById('hf-name').value.trim(),
      participant_email: document.getElementById('hf-email').value.trim(),
      num_occupants: parseInt(document.getElementById('hf-occupants').value, 10) || 1,
      home_type: document.getElementById('hf-type').value,
      devices,
    }) });
    document.getElementById('home-form').style.display = 'none';
    document.getElementById('home-form').reset();
    document.getElementById('hf-devices').innerHTML = '';
    fb.textContent = '';
    showHomeResult(
      `<strong>${h(res.home_name)}</strong> created as <strong>${h(res.mqtt_username)}</strong>.` +
      (res.temporary_app_password ? ` App login: <strong>${h(res.user_email)}</strong> / temporary password <strong>${h(res.temporary_app_password)}</strong>.` : ` App login: ${h(res.user_email)} (existing account).`) +
      `<br>Paste this into the WattWise Publisher add-on on the participant's Raspberry Pi. <span style="color:#f59e0b">The MQTT password is shown only now.</span>`,
      res.publisher_yaml, `wattwise_publisher_${res.mqtt_username}.yaml`);
    loadHomes();
  } catch (err) {
    fb.textContent = `❌ ${err.message}`; fb.className = 'form-feedback error';
  } finally { btn.disabled = false; }
}

function initHomesUi() {
  document.getElementById('btn-refresh-homes').addEventListener('click', loadHomes);
  document.getElementById('btn-add-home').addEventListener('click', () => {
    const form = document.getElementById('home-form');
    form.style.display = form.style.display === 'none' ? 'block' : 'none';
    if (form.style.display === 'block' && !document.querySelector('#hf-devices .hf-device')) addHomeDeviceRow('kettle');
  });
  document.getElementById('hf-add-device').addEventListener('click', () => addHomeDeviceRow('microwave'));
  document.getElementById('hf-cancel').addEventListener('click', () => { document.getElementById('home-form').style.display = 'none'; });
  document.getElementById('home-form').addEventListener('submit', submitHomeForm);
  document.getElementById('home-result-close').addEventListener('click', () => { document.getElementById('home-result').style.display = 'none'; });
  document.getElementById('home-result-copy').addEventListener('click', async () => {
    const ta = document.getElementById('home-result-yaml');
    try { await navigator.clipboard.writeText(ta.value); } catch { ta.select(); document.execCommand('copy'); }
    toast('Config copied', 'success');
  });
  document.getElementById('home-result-download').addEventListener('click', () => {
    const ta = document.getElementById('home-result-yaml');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([ta.value], { type: 'text/yaml' }));
    a.download = ta.dataset.filename || 'wattwise_publisher.yaml';
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(a.href);
  });
  document.getElementById('homes-tbody').addEventListener('click', async e => {
    const btn = e.target.closest('[data-home-act]');
    if (!btn) return;
    const id = btn.dataset.home;
    try {
      if (btn.dataset.homeAct === 'config') {
        const res = await api(`/api/admin/homes/${id}/publisher-config`);
        showHomeResult(`Config for <strong>${h(res.mqtt_username)}</strong>. The MQTT password is not stored in readable form — use the one issued at creation, or “New password”.`,
          res.publisher_yaml, `wattwise_publisher_${res.mqtt_username}.yaml`);
      } else if (btn.dataset.homeAct === 'rotate') {
        if (!confirm(`Issue a new MQTT password for ${btn.dataset.name}? Its Raspberry Pi stops publishing until the new config is pasted in.`)) return;
        const res = await api(`/api/admin/homes/${id}/rotate-credentials`, { method: 'POST' });
        showHomeResult(`New MQTT password issued for <strong>${h(res.mqtt_username)}</strong>. <span style="color:#f59e0b">Shown only now</span> — paste this config into the Pi and restart the add-on.`,
          res.publisher_yaml, `wattwise_publisher_${res.mqtt_username}.yaml`);
      }
    } catch (err) { toast(err.message, 'error'); }
  });
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
    notifications: 'Notifications', decisions: 'Decisions & Responses', backup: 'Backups', audit: 'Audit Log',
  };
  document.getElementById('page-title').textContent = titles[section] || section;

  // Load section data
  switch (section) {
    case 'dashboard': loadDashboard(); break;
    case 'users': loadUsers(1); break;
    case 'personas': loadPersonas(); break;
    case 'rankings': loadRankings(); break;
    case 'analytics': loadAnalytics(); loadSankey(); break;
    case 'devices': loadHomes(); loadDevices(); loadMqttBrokerStats(); break;
    case 'notifications': loadTemplates(); loadNotifBreakdown(); break;
    case 'decisions': loadDecisionsSection(); break;
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

function createRadarChart(id, labels, datasets, opts = {}) {
  destroyChart(id);
  const ctx = document.getElementById(id)?.getContext('2d');
  if (!ctx) return;
  _charts[id] = new Chart(ctx, {
    type: 'radar',
    data: { labels, datasets },
    options: {
      responsive: true,
      plugins: { legend: { position: 'bottom', labels: { color: '#94a3b8', font: { size: 12 }, padding: 12 } } },
      scales: {
        r: {
          suggestedMin: 0, suggestedMax: 100,
          angleLines: { color: 'rgba(255,255,255,0.08)' },
          grid: { color: 'rgba(255,255,255,0.08)' },
          pointLabels: { color: '#94a3b8', font: { size: 11 } },
          ticks: { color: '#6b7280', backdropColor: 'transparent', stepSize: 25 },
        },
      },
      ...opts,
    },
  });
}

// ── Dashboard ─────────────────────────────────────────────────
function _energyPeriodQuery() {
  // Dropdown values are "h:N" (hours) or "d:N" (days). Returns {query, title}.
  const raw = document.getElementById('energy-period-select')?.value || 'd:7';
  const [unit, nStr] = raw.split(':');
  const n = Math.max(1, parseInt(nStr, 10) || 7);
  if (unit === 'h') {
    return {
      query: `hours=${n}`,
      title: `Community Energy (Last ${n} hour${n > 1 ? 's' : ''})`,
      mode: 'hour',
    };
  }
  return {
    query: `days=${n}`,
    title: `Community Energy (${n} days)`,
    mode: 'day',
  };
}

async function loadDashboard() {
  try {
    loadPipelineHealth();
    const period = _energyPeriodQuery();
    const titleEl = document.getElementById('energy-chart-title');
    if (titleEl) titleEl.textContent = period.title;

    const [dash, decisions, energy] = await Promise.all([
      api('/api/admin/dashboard'),
      api(`/api/admin/analytics/decisions?cohort=${_cohort}`),
      api(`/api/admin/analytics/energy?${period.query}`),
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
      document.getElementById('di-effectiveness').textContent = decisions.avg_effectiveness_score != null ? `${decisions.avg_effectiveness_score.toFixed(0)}%` : '—%';
      document.getElementById('di-response-time').textContent = decisions.avg_response_time_seconds != null ? fmtDuration(decisions.avg_response_time_seconds) : '—';
      document.getElementById('di-split').textContent = `${(decisions.accepted || 0) + (decisions.custom_action || 0)} / ${decisions.deferred || 0} / ${decisions.rejected || 0}`;
      paintCohortLabels();
    }

    if (energy?.length) {
      const isHourly = period.mode === 'hour';
      const labels = energy.map(r => {
        if (!isHourly) return r.date;
        const d = new Date(r.date);
        return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
      });
      createLineChart('chart-energy', labels, [
        {
          label: 'Total kWh',
          data: energy.map(r => r.total_kwh),
          borderColor: '#3b82f6',
          backgroundColor: 'rgba(59,130,246,0.1)',
          fill: true,
          tension: 0.4,
          pointRadius: isHourly ? 2 : 4,
        },
        {
          label: 'Cost £',
          data: energy.map(r => r.total_cost_gbp),
          borderColor: '#10b981',
          backgroundColor: 'rgba(16,185,129,0.08)',
          fill: true,
          tension: 0.4,
          pointRadius: isHourly ? 2 : 4,
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
    await loadDeviceTimeseries();
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
    const resp = await api(`/api/admin/rankings?period=${period}`);
    const rows = resp?.rankings || [];
    if (!rows.length) { el.innerHTML = '<div class="loading-row">No ranking data yet</div>'; return; }
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

// ── Admin Notification Breakdown ──────────────────────────────
const SEVERITY_COLORS = {
  INFO:     '#3b82f6',
  WARNING:  '#f59e0b',
  ALERT:    '#ef4444',
  CRITICAL: '#dc2626',
};
const APPLIANCE_COLORS = [
  '#10b981', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6',
  '#ec4899', '#14b8a6', '#f97316', '#06b6d4', '#a855f7',
];

async function loadNotifBreakdown() {
  try {
    const data = await api('/api/admin/notifications/stats/breakdown');
    if (!data) return;

    // Summary KPI tiles
    const p = data.by_period || {};
    const s = data.state || {};
    const sum = document.getElementById('notif-breakdown-summary');
    if (sum) {
      sum.innerHTML = [
        ['Last 24h', p.last_24h ?? 0, '#3b82f6'],
        ['Last 7 days', p.last_7d ?? 0, '#10b981'],
        ['Last 30 days', p.last_30d ?? 0, '#8b5cf6'],
        ['All time', p.all_time ?? 0, '#f59e0b'],
        ['Unread', s.unread ?? 0, '#ef4444'],
        ['Dismissed', s.dismissed ?? 0, '#94a3b8'],
      ].map(([label, v, c]) => `
        <div style="background:rgba(255,255,255,0.03);padding:10px 12px;border-radius:8px;border-left:3px solid ${c}">
          <div style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.5px">${label}</div>
          <div style="font-size:22px;font-weight:700;color:${c};margin-top:2px">${v}</div>
        </div>
      `).join('');
    }

    // Severity donut
    if (data.by_severity?.length) {
      createDonutChart(
        'chart-notif-by-severity',
        data.by_severity.map(b => b.severity),
        data.by_severity.map(b => b.count),
        data.by_severity.map(b => SEVERITY_COLORS[b.severity] || '#6b7280'),
      );
    }

    // Type donut
    if (data.by_type?.length) {
      createDonutChart(
        'chart-notif-by-type',
        data.by_type.map(b => b.type),
        data.by_type.map(b => b.count),
        data.by_type.map((_, i) => APPLIANCE_COLORS[i % APPLIANCE_COLORS.length]),
      );
    } else {
      destroyChart('chart-notif-by-type');
    }

    // Appliance donut
    if (data.by_appliance?.length) {
      createDonutChart(
        'chart-notif-by-appliance',
        data.by_appliance.map(b => b.appliance),
        data.by_appliance.map(b => b.count),
        data.by_appliance.map((_, i) => APPLIANCE_COLORS[i % APPLIANCE_COLORS.length]),
      );
    } else {
      destroyChart('chart-notif-by-appliance');
    }

    // Top recipients table
    const tbody = document.getElementById('notif-top-users-tbody');
    if (tbody) {
      if (!data.top_users?.length) {
        tbody.innerHTML = '<tr><td colspan="3" class="loading-row">No notifications sent yet</td></tr>';
      } else {
        tbody.innerHTML = data.top_users.map(u => `
          <tr>
            <td>${DOMPurify.sanitize(u.name)}</td>
            <td><span style="font-size:11px;color:#94a3b8">${DOMPurify.sanitize(u.email)}</span></td>
            <td style="text-align:right"><strong>${u.count}</strong></td>
          </tr>
        `).join('');
      }
    }
  } catch (err) {
    console.warn('Notification breakdown load failed:', err.message);
  }
}

// ── CSV Export Helper ─────────────────────────────────────────
function downloadCsv(filename, header, rows) {
  const escape = (v) => {
    if (v === null || v === undefined) return '';
    const s = String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [header.join(',')];
  rows.forEach(r => lines.push(r.map(escape).join(',')));
  const blob = new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(url); }, 100);
}

// ── MQTT Broker Health ────────────────────────────────────────
let _mqttRefreshTimer = null;

async function loadMqttBrokerStats() {
  try {
    const data = await api('/api/admin/mqtt/stats');
    const statusEl = document.getElementById('mqtt-broker-status');
    if (statusEl) {
      const ok = data.broker_connected;
      statusEl.textContent = ok ? '● connected' : '● disconnected';
      statusEl.style.background = ok ? 'rgba(16,185,129,.18)' : 'rgba(239,68,68,.18)';
      statusEl.style.color = ok ? '#10b981' : '#ef4444';
    }

    const m = data.metrics || {};
    const fmt = (v, kind = 'num') => {
      if (v === null || v === undefined) return '—';
      if (kind === 'uptime') {
        // value looks like "12345 seconds" — extract digits
        const sec = parseInt(String(v).replace(/[^\d]/g, ''), 10);
        if (!sec) return '—';
        const d = Math.floor(sec / 86400);
        const h = Math.floor((sec % 86400) / 3600);
        const m = Math.floor((sec % 3600) / 60);
        return d > 0 ? `${d}d ${h}h` : h > 0 ? `${h}h ${m}m` : `${m}m`;
      }
      if (kind === 'bytes') {
        const n = Number(v);
        if (n > 1024 * 1024) return (n / (1024 * 1024)).toFixed(1) + ' MB';
        if (n > 1024) return (n / 1024).toFixed(1) + ' KB';
        return n + ' B';
      }
      return typeof v === 'number' ? v.toLocaleString('en-GB') : v;
    };

    const tiles = [
      ['Uptime',           fmt(m.uptime, 'uptime'),           '#10b981'],
      ['Connected clients', fmt(m.clients_connected),         '#3b82f6'],
      ['Total ever',        fmt(m.clients_total),             '#8b5cf6'],
      ['Subscriptions',     fmt(m.subscriptions_count),       '#f59e0b'],
      ['Msgs received',     fmt(m.messages_received),         '#3b82f6'],
      ['Msgs sent',         fmt(m.messages_sent),             '#10b981'],
      ['Retained',          fmt(m.retained_count),            '#94a3b8'],
      ['Bytes received',    fmt(m.bytes_received, 'bytes'),   '#3b82f6'],
      ['Bytes sent',        fmt(m.bytes_sent,     'bytes'),   '#10b981'],
      ['Msgs in (1m avg)',  fmt(m.load_msg_in_1min),          '#06b6d4'],
      ['Msgs out (1m avg)', fmt(m.load_msg_out_1min),         '#06b6d4'],
      ['Version',           fmt(m.version),                   '#94a3b8'],
    ];

    const grid = document.getElementById('mqtt-broker-grid');
    if (grid) {
      grid.innerHTML = tiles.map(([label, val, c]) => `
        <div style="background:rgba(255,255,255,0.03);padding:10px 12px;border-radius:8px;border-left:3px solid ${c}">
          <div style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.5px">${label}</div>
          <div style="font-size:18px;font-weight:700;color:${c};margin-top:2px">${val}</div>
        </div>
      `).join('');
    }

    const meta = document.getElementById('mqtt-broker-meta');
    if (meta) {
      const last = data.last_update ? new Date(data.last_update).toLocaleTimeString('en-GB') : 'never';
      meta.textContent = `${data.topics_cached} $SYS topics cached · last update ${last}`;
    }
  } catch (err) {
    console.warn('MQTT broker stats:', err.message);
  }
}

function startMqttBrokerAutoRefresh() {
  if (_mqttRefreshTimer) clearInterval(_mqttRefreshTimer);
  _mqttRefreshTimer = setInterval(() => {
    const sec = document.getElementById('section-devices');
    if (sec && sec.classList.contains('active')) loadMqttBrokerStats();
  }, 10_000);
}

// ── Decision Simulator ────────────────────────────────────────
async function runDecisionsSimulator() {
  const fb = document.getElementById('decisions-feedback');
  const days = parseInt(document.getElementById('decisions-window-days')?.value || '7', 10);
  const accept = parseFloat(document.getElementById('decisions-accept-rate')?.value || '0.55');
  const defer = parseFloat(document.getElementById('decisions-defer-rate')?.value || '0.20');
  if (!confirm(`Generate synthetic decisions on notifications from the last ${days} days?\nAccept ${(accept*100).toFixed(0)}% · Defer ${(defer*100).toFixed(0)}% · Reject ${((1-accept-defer)*100).toFixed(0)}%`)) return;

  fb.textContent = 'Simulating…';
  fb.className = 'form-feedback';
  try {
    const url = `/api/admin/decisions/simulate?notification_window_days=${days}&accept_rate=${accept}&defer_rate=${defer}`;
    const res = await api(url, { method: 'POST' });
    const c = res.by_type || {};
    fb.textContent = `✅ ${res.created} decisions created — accepted=${c.ACCEPTED || 0} · deferred=${c.DEFERRED || 0} · rejected=${c.REJECTED || 0}`;
    fb.className = 'form-feedback success';
    // Refresh the dashboard so the Decision Impact card updates
    if (typeof loadDashboard === 'function') loadDashboard();
  } catch (err) {
    fb.textContent = `❌ ${err.message}`;
    fb.className = 'form-feedback error';
  }
}

// ── Live Device Telemetry ─────────────────────────────────────
const DEVICE_PALETTE = [
  '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
  '#ec4899', '#14b8a6', '#f97316', '#06b6d4', '#a855f7',
  '#22c55e', '#eab308', '#0ea5e9', '#f43f5e', '#6366f1',
];
let _deviceTsTimer = null;
let _deviceTsHomeMap = null;   // {home_id: home_name} cached after first fetch
const DEVICE_TS_MAX_DATASETS = 30;  // cap to keep the chart readable

function _populateDeviceTsHomeDropdown(devices) {
  // Build the home filter from actual {home_id, home_name} pairs returned
  // by the timeseries endpoint itself — no extra round-trip needed.
  const sel = document.getElementById('device-ts-home');
  if (!sel) return;
  const current = sel.value;
  const pairs = {};
  (devices || []).forEach(d => {
    if (d.home_id != null) pairs[d.home_id] = d.home_name;
  });
  const sorted = Object.entries(pairs).sort((a, b) => a[1].localeCompare(b[1]));
  _deviceTsHomeMap = pairs;
  sel.innerHTML = '<option value="">All homes</option>' + sorted
    .map(([id, name]) => `<option value="${id}">${DOMPurify.sanitize(name)}</option>`)
    .join('');
  // Restore selection if it still exists
  if (current && pairs[current]) sel.value = current;
}

async function loadDeviceTimeseries() {
  const status = document.getElementById('device-ts-status');
  const titleEl = document.getElementById('device-ts-title');
  const hours = parseInt(document.getElementById('device-ts-period')?.value || '24', 10);
  const homeId = document.getElementById('device-ts-home')?.value || '';

  if (titleEl) {
    const label = hours >= 24 && hours % 24 === 0
      ? `${hours / 24} day${hours === 24 ? '' : 's'}`
      : `${hours} hour${hours === 1 ? '' : 's'}`;
    titleEl.textContent = `Live Device Telemetry (Last ${label})`;
  }
  if (status) status.textContent = 'Loading…';

  try {
    // First populate the home dropdown if we haven't yet — by fetching with NO filter.
    if (_deviceTsHomeMap === null) {
      const allData = await api(`/api/admin/analytics/device-timeseries?hours=${hours}`);
      _populateDeviceTsHomeDropdown(allData?.devices || []);
    }

    let url = `/api/admin/analytics/device-timeseries?hours=${hours}`;
    if (homeId) url += `&home_id=${encodeURIComponent(homeId)}`;

    // Fetch device timeseries + anomalies in parallel (anomalies are optional)
    const showAnomalies = document.getElementById('device-ts-anomalies')?.checked !== false;
    const [data, anomaliesData] = await Promise.all([
      api(url),
      showAnomalies
        ? api(`/api/admin/analytics/anomalies?hours=${hours}${homeId ? '&home_id=' + encodeURIComponent(homeId) : ''}`)
            .catch(() => ({ anomalies: [] }))
        : Promise.resolve({ anomalies: [] }),
    ]);
    let devices = data?.devices || [];
    const anomalies = anomaliesData?.anomalies || [];

    // Index anomalies by (device_id, hour_start) for fast lookup during render
    const anomalyKey = new Set(anomalies.map(a => `${a.device_id}|${a.hour_start}`));

    if (!devices.length) {
      destroyChart('chart-device-ts');
      if (status) status.textContent = 'No hourly data in window';
      return;
    }

    // When showing "All homes", pick top N devices by total kWh so the
    // chart doesn't become a 159-line rainbow.
    let truncated = false;
    if (devices.length > DEVICE_TS_MAX_DATASETS) {
      devices = devices
        .map(d => ({ ...d, _sumKwh: d.points.reduce((a, p) => a + (p.kwh || 0), 0) }))
        .sort((a, b) => b._sumKwh - a._sumKwh)
        .slice(0, DEVICE_TS_MAX_DATASETS);
      truncated = true;
    }

    // Build unified x-axis from union of all device timestamps
    const tsSet = new Set();
    devices.forEach(d => d.points.forEach(p => tsSet.add(p.ts)));
    const labels = Array.from(tsSet).sort();
    const labelText = labels.map(t => {
      const d = new Date(t);
      if (hours <= 48) return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
      return d.toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
    });

    const datasets = devices.map((dev, i) => {
      const lookup = Object.fromEntries(dev.points.map(p => [p.ts, p.kwh]));
      // Per-point colour override: highlight anomalous hours red
      const pointBg = labels.map(t =>
        anomalyKey.has(`${dev.device_id}|${t}`) ? '#ef4444' : DEVICE_PALETTE[i % DEVICE_PALETTE.length]
      );
      const pointRadius = labels.map(t =>
        anomalyKey.has(`${dev.device_id}|${t}`) ? 5 : (hours <= 12 ? 2 : 0)
      );
      return {
        label: `${dev.home_name} · ${dev.device_name}`,
        data: labels.map(t => lookup[t] ?? null),
        borderColor: DEVICE_PALETTE[i % DEVICE_PALETTE.length],
        backgroundColor: 'transparent',
        pointBackgroundColor: pointBg,
        pointBorderColor: pointBg,
        pointRadius: pointRadius,
        tension: 0.3,
        spanGaps: true,
        borderWidth: 2,
      };
    });

    // Anomaly summary line
    const summaryEl = document.getElementById('device-ts-anomaly-summary');
    if (summaryEl) {
      if (anomalies.length > 0) {
        const top = anomalies[0];
        summaryEl.textContent = `⚠ ${anomalies.length} anomaly hour${anomalies.length > 1 ? 's' : ''} highlighted — top: ${top.home_name} · ${top.device_name} at ${new Date(top.hour_start).toLocaleString('en-GB', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: 'short' })} (${top.ratio}× baseline)`;
      } else {
        summaryEl.textContent = '';
      }
    }

    createLineChart('chart-device-ts', labelText, datasets, {
      interaction: { mode: 'nearest', axis: 'x', intersect: false },
      plugins: {
        legend: {
          display: true,
          position: 'bottom',
          align: 'start',
          labels: {
            color: '#cbd5e1',
            font: { size: 11 },
            boxWidth: 12,
            boxHeight: 4,
            padding: 8,
            usePointStyle: false,
          },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: ${(ctx.parsed.y ?? 0).toFixed(4)} kWh`,
          },
        },
      },
      scales: {
        x: { ticks: { color: '#6b7280', maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } },
        y: { ticks: { color: '#6b7280', callback: v => `${v} kWh` }, beginAtZero: true },
      },
    });

    if (status) {
      const updated = new Date().toLocaleTimeString('en-GB');
      const filterLabel = homeId
        ? `${_deviceTsHomeMap?.[homeId] || 'home'} · ${devices.length} devices`
        : truncated
          ? `top ${devices.length} of all homes`
          : `${devices.length} devices`;
      status.textContent = `${filterLabel} · updated ${updated}`;
    }
  } catch (err) {
    console.warn('Device TS load failed:', err.message);
    if (status) status.textContent = 'Load failed: ' + err.message;
  }
}

function startDeviceTimeseriesAutoRefresh() {
  if (_deviceTsTimer) clearInterval(_deviceTsTimer);
  _deviceTsTimer = setInterval(() => {
    const dashSection = document.getElementById('section-dashboard');
    if (dashSection && dashSection.classList.contains('active')) {
      loadDeviceTimeseries().catch(() => {});
    }
  }, 30_000);
}

// ── Users ─────────────────────────────────────────────────────
async function loadUsers(page = 1) {
  _currentPage.users = page;
  const search = document.getElementById('user-search')?.value || '';
  const personaId = document.getElementById('persona-filter')?.value || '';
  const tbody = document.getElementById('users-tbody');
  tbody.innerHTML = '<tr><td colspan="7" class="loading-row">Loading…</td></tr>';

  try {
    let url = `/api/admin/users?page=${page}&limit=20&cohort=${_cohort}`;
    if (search) url += `&search=${encodeURIComponent(search)}`;
    if (personaId) url += `&persona_id=${personaId}`;
    const users = await api(url);

    if (!users?.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="loading-row">No users found</td></tr>';
      return;
    }

    tbody.innerHTML = users.map(u => {
      const pc = _personaBadgeClass[u.persona_name] || 'diseng';
      return `
        <tr data-user-id="${u.id}">
          <td><input type="checkbox" class="user-checkbox" data-uid="${u.id}" ${_selectedUserIds.has(u.id) ? 'checked' : ''}/></td>
          <td>${h(u.name)}${u.is_synthetic ? ' <span class="tag-sim">synthetic</span>' : ''}</td>
          <td>${h(u.email)}</td>
          <td>${u.persona_name ? `<span class="badge badge-${pc}">${h(u.persona_name)}</span>` : '<span class="badge badge-diseng">None</span>'}</td>
          <td>${u.last_login_at ? new Date(u.last_login_at + 'Z').toLocaleDateString('en-GB') : '—'}</td>
          <td><span class="badge badge-${u.notifications_enabled ? 'enabled' : 'disabled'}">${u.notifications_enabled ? '✓ On' : '✗ Off'}</span></td>
          <td>
            <button class="btn-sm btn-outline" data-user-act="details" data-uid="${u.id}">Details</button>
            <button class="btn-sm btn-outline" data-user-act="toggle" data-uid="${u.id}">Toggle Notif</button>
            <button class="btn-sm" title="Inline insights" data-user-act="drill" data-uid="${u.id}" data-name="${h(u.name)}">🔍</button>
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
        <div class="detail-row"><span class="detail-key">Name</span><span class="detail-val">${h(u.name)}${u.is_synthetic ? ' <span class="tag-sim">synthetic</span>' : ''}</span></div>
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
        <div class="detail-row"><span class="detail-key">Done / Later / Skipped</span><span class="detail-val">${d.decision_impact?.accepted ?? 0} / ${d.decision_impact?.deferred ?? 0} / ${d.decision_impact?.rejected ?? 0}</span></div>
        <div class="detail-row"><span class="detail-key">Avg Response Time</span><span class="detail-val">${fmtDuration(d.decision_impact?.avg_response_time_seconds)}</span></div>
        <div class="detail-row"><span class="detail-key">Avg Rating</span><span class="detail-val">${d.decision_impact?.avg_satisfaction ?? '—'}</span></div>
        <div class="detail-row"><span class="detail-key">Energy Saved</span><span class="detail-val" style="color:var(--success)">${d.decision_impact?.total_energy_saved_kwh ?? 0} kWh</span></div>
        <div class="detail-row"><span class="detail-key">Cost Saved</span><span class="detail-val" style="color:var(--success)">£${d.decision_impact?.total_cost_saved_gbp ?? 0}</span></div>
        <div class="detail-row"><span class="detail-key">Avg Effectiveness</span><span class="detail-val">${d.decision_impact?.avg_effectiveness_score ? `${d.decision_impact.avg_effectiveness_score}%` : '—'}</span></div>
      </div>

      <div class="detail-section">
        <div class="detail-section-title">Homes</div>
        ${d.homes?.map(hm => `<div class="detail-row"><span class="detail-key">${h(hm.name)} <span style="color:#9ca3af">#${hm.id}</span></span><span class="detail-val">${h(hm.home_type)} · ${h(hm.num_occupants)} occupant(s)</span></div>
          <div class="dx-note" style="max-width:none;margin:-2px 0 6px">${(hm.devices || []).map(dv => h(dv.name)).join(', ') || 'No devices'}</div>`).join('') || '<div class="detail-row"><span class="detail-key">No homes registered</span></div>'}
      </div>

      <div class="detail-section">
        <div class="detail-section-title">Recent alerts and responses</div>
        ${(d.recent_notifications || []).map(n => `<div class="detail-row" style="align-items:flex-start">
            <span class="detail-key" style="max-width:62%">${h(n.title)}<div class="dx-note">${fmtWhen(n.created_at)} · ${n.source === 'ADMIN' ? 'admin send' : h(n.type)}${n.opened_at ? ' · opened' : n.read ? ' · seen' : ' · not seen'}</div></span>
            <span class="detail-val" style="text-align:right">${n.decision ? (DECISION_LABELS[n.decision.decision_type] || h(n.decision.decision_type)) + (n.decision.is_simulated ? ' <span class="tag-sim">simulated</span>' : '') : (n.requires_user_action ? '<span style="color:#f59e0b">no response</span>' : '—')}${n.decision?.action_taken ? `<div class="dx-note">${h(n.decision.action_taken)}</div>` : ''}</span>
          </div>`).join('') || '<div class="detail-row"><span class="detail-key">No alerts yet</span></div>'}
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
      <div class="persona-card" data-persona="${DOMPurify.sanitize(p.name)}" data-persona-id="${p.id}">
        <div class="persona-name">${DOMPurify.sanitize(p.name)}</div>
        <div class="persona-label">USERS</div>
        <div class="persona-count" style="color:${_personaColors[p.name] || '#6b7280'}">${p.user_count}</div>
        <div class="persona-desc">${DOMPurify.sanitize(p.description || '')}</div>
        <div style="margin-top:10px;display:flex;gap:6px">
          <button class="btn-sm" onclick="event.stopPropagation(); openPersonaMembers(${p.id}, '${(p.name || '').replace(/'/g, '\\\'')}');">View members</button>
          <button class="btn-sm" onclick="event.stopPropagation(); filterUsersByPersona(${p.id});">In Users tab</button>
        </div>
      </div>`).join('');

    // Update persona filter dropdown
    const filter = document.getElementById('persona-filter');
    if (filter) {
      filter.innerHTML = '<option value="">All Personas</option>' +
        personas.map(p => `<option value="${p.id}">${DOMPurify.sanitize(p.name)}</option>`).join('');
    }

    await Promise.all([loadPersonaComparisonChart(), loadPersonaHistoryChart()]);
  } catch (err) { toast('Personas load failed: ' + err.message, 'error'); }
}

async function loadPersonaHistoryChart() {
  const period = document.getElementById('persona-history-period')?.value || 'WEEKLY';
  const buckets = parseInt(document.getElementById('persona-history-buckets')?.value || '12', 10);
  const titleEl = document.getElementById('persona-history-title');
  if (titleEl) {
    const periodLabel = { DAILY: 'Day', WEEKLY: 'Week', MONTHLY: 'Month' }[period] || period;
    titleEl.textContent = `Persona Distribution Over Time (last ${buckets} ${periodLabel.toLowerCase()}${buckets === 1 ? '' : 's'})`;
  }
  try {
    const data = await api(`/api/admin/personas/history?period=${period}&buckets=${buckets}`);
    if (!data?.series?.length) return;

    const labels = data.series.map(s => {
      const d = new Date(s.bucket + 'T00:00:00');
      if (period === 'MONTHLY') return d.toLocaleDateString('en-GB', { month: 'short', year: '2-digit' });
      return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
    });

    const personaOrder = ['Eco Champion', 'Active Improver', 'Steady User', 'High Consumer', 'Disengaged'];
    const datasets = personaOrder.map(name => {
      const colour = _personaColors[name] || '#6b7280';
      return {
        label: name,
        data: data.series.map(s => s.counts[name] || 0),
        backgroundColor: colour,
        borderColor: colour,
        stack: 'personas',
      };
    });

    destroyChart('chart-persona-history');
    const ctx = document.getElementById('chart-persona-history')?.getContext('2d');
    if (!ctx) return;
    _charts['chart-persona-history'] = new Chart(ctx, {
      type: 'bar',
      data: { labels, datasets },
      options: {
        responsive: true,
        plugins: {
          legend: { position: 'bottom', labels: { color: '#cbd5e1', font: { size: 11 }, padding: 10 } },
          tooltip: { mode: 'index', intersect: false },
        },
        scales: {
          x: { stacked: true, ticks: { color: '#6b7280' }, grid: { color: 'rgba(255,255,255,0.04)' } },
          y: { stacked: true, ticks: { color: '#6b7280', precision: 0 }, grid: { color: 'rgba(255,255,255,0.04)' }, beginAtZero: true },
        },
      },
    });
  } catch (err) { console.warn('Persona history:', err.message); }
}

async function openPersonaMembers(personaId, personaName) {
  const card = document.getElementById('persona-members-card');
  const tbody = document.getElementById('persona-members-tbody');
  const titleEl = document.getElementById('persona-members-title');
  if (!card || !tbody) return;
  card.style.display = 'block';
  titleEl.textContent = `Members of "${personaName}"`;
  tbody.innerHTML = '<tr><td colspan="7" class="loading-row">Loading…</td></tr>';
  try {
    const members = await api(`/api/admin/personas/${personaId}/users?limit=100`);
    if (!members?.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="loading-row">No members in this persona</td></tr>';
      return;
    }
    tbody.innerHTML = members.map(m => `
      <tr>
        <td>${DOMPurify.sanitize(m.name)}</td>
        <td><span style="font-size:11px;color:#94a3b8">${DOMPurify.sanitize(m.email)}</span></td>
        <td><strong style="color:var(--brand)">${m.avg_overall_score?.toFixed(1) ?? '—'}</strong></td>
        <td>${m.avg_efficiency?.toFixed(0) ?? '—'}%</td>
        <td>${m.avg_adherence?.toFixed(0) ?? '—'}%</td>
        <td>${m.avg_kwh_per_day?.toFixed(2) ?? '—'}</td>
        <td>${m.ranking_days_in_window}</td>
      </tr>`).join('');
    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
  } catch (err) { toast('Member load failed: ' + err.message, 'error'); }
}

function _hexToRgba(hex, a) {
  const h = (hex || '#6b7280').replace('#', '');
  const full = h.length === 3 ? h.split('').map(c => c + c).join('') : h;
  const n = parseInt(full, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

async function loadPersonaComparisonChart() {
  const days = document.getElementById('persona-comparison-days')?.value || 30;
  try {
    const data = await api(`/api/admin/analytics/persona-comparison?days=${days}`);
    if (!data?.length) return;

    // Radar of behavioural profiles — one shape per persona, so groups look distinct
    // even when their user counts are similar (a flat grouped bar hid the differences).
    const maxKwh = Math.max(...data.map(r => r.avg_daily_kwh || 0), 0.001);
    const axes = ['Efficiency', 'Goal Adherence', 'Decision Response', 'Low Consumption'];
    const datasets = data.map(r => {
      const c = _personaColors[r.persona] || '#6b7280';
      const lowConsumption = Math.max(0, Math.round(100 * (1 - (r.avg_daily_kwh || 0) / maxKwh)));
      return {
        label: `${r.persona} (${r.user_count})`,
        data: [r.avg_efficiency_score, r.avg_goal_adherence, r.avg_decision_score, lowConsumption],
        borderColor: c,
        backgroundColor: _hexToRgba(c, 0.14),
        borderWidth: 2,
        pointBackgroundColor: c,
        pointRadius: 3,
      };
    });
    createRadarChart('chart-persona-compare', axes, datasets);
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
  initDeviceDeepDive();
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

// ── Single-Device Deep-Dive ───────────────────────────────────
async function initDeviceDeepDive() {
  const sel = document.getElementById('dd-device-select');
  if (!sel || sel.dataset.loaded) return;
  try {
    const devices = await api('/api/admin/devices/status');
    sel.innerHTML = (devices || []).map(d =>
      `<option value="${d.device_id}">${DOMPurify.sanitize(d.device_name)} — ${DOMPurify.sanitize(d.user)} (${DOMPurify.sanitize(d.home)})</option>`).join('');
    sel.dataset.loaded = '1';
  } catch (err) { console.warn('deep-dive devices:', err.message); }
}

async function loadDeviceReport() {
  const sel = document.getElementById('dd-device-select');
  const did = sel?.value;
  if (!did) { toast('Pick a device', 'error'); return; }
  const days = parseInt(document.getElementById('dd-days')?.value || '14');
  try {
    const r = await api(`/api/admin/analytics/device/${did}/report?days=${days}`);
    document.getElementById('dd-totals').textContent =
      `${r.user.name} · ${r.totals.total_kwh} kWh · £${r.totals.total_cost_gbp} · ${r.totals.avg_daily_kwh} kWh/day avg`;
    const daily = r.daily || [];
    createLineChart('chart-dd-daily', daily.map(p => p.date), [
      { label: 'kWh/day', data: daily.map(p => p.total_kwh), borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.08)', fill: true, tension: 0.35 },
      { label: 'Peak W', data: daily.map(p => p.peak_watts), borderColor: '#f59e0b', backgroundColor: 'transparent', yAxisID: 'y2', tension: 0.35 },
    ], { scales: { y2: { position: 'right', grid: { display: false }, ticks: { color: '#f59e0b' } } } });
    const prof = r.hourly_profile || [];
    createBarChart('chart-dd-profile', prof.map(p => p.hour + ':00'), [
      { label: 'Avg W by hour-of-day', data: prof.map(p => p.avg_watts), backgroundColor: 'rgba(16,185,129,0.7)', borderRadius: 3 },
    ]);
    toast('Loaded device report', 'success');
  } catch (err) { toast('Device report failed: ' + err.message, 'error'); }
}

// ── Advanced Comparison ───────────────────────────────────────
let _lastComparisonData = null;

async function initAdvancedComparison() {
  const typeSelect = document.getElementById('compare-entity-type');
  const targetContainer = document.getElementById('compare-entity-ids');
  
  // Set default dates
  const today = new Date().toISOString().slice(0,10);
  const monthAgo = new Date(Date.now() - 30 * 86400000).toISOString().slice(0,10);
  document.getElementById('compare-start').value = monthAgo;
  document.getElementById('compare-end').value = today;

  const populateTargets = async () => {
    targetContainer.innerHTML = '<div style="padding:10px; color:var(--text-muted)">Loading...</div>';
    if (typeSelect.value === 'user') {
      const users = await api('/api/admin/users?limit=1000');
      if (users && users.length) {
        targetContainer.innerHTML = users.map(u => 
          `<label class="checkbox-label"><input type="checkbox" value="${u.id}"> ${DOMPurify.sanitize(u.name)}</label>`
        ).join('');
      } else {
        targetContainer.innerHTML = '<div style="padding:10px; color:var(--text-muted)">No users found</div>';
      }
      document.querySelectorAll('.device-metric').forEach(el => el.style.display = 'none');
    } else {
      const devices = await api('/api/admin/devices/status');
      if (devices && devices.length) {
        targetContainer.innerHTML = devices.map(d => 
          `<label class="checkbox-label"><input type="checkbox" value="${d.device_id}"> ${DOMPurify.sanitize(d.device_name)} (${DOMPurify.sanitize(d.user)})</label>`
        ).join('');
      } else {
        targetContainer.innerHTML = '<div style="padding:10px; color:var(--text-muted)">No devices found</div>';
      }
      document.querySelectorAll('.device-metric').forEach(el => el.style.display = 'block');
    }
  };

  typeSelect.addEventListener('change', populateTargets);
  populateTargets(); // auto-load on start

  document.getElementById('btn-run-compare').addEventListener('click', async () => {
    const entity_type = typeSelect.value;
    const entity_ids = Array.from(document.querySelectorAll('#compare-entity-ids input:checked')).map(cb => parseInt(cb.value));
    const metrics = Array.from(document.querySelectorAll('#compare-metric input:checked')).map(cb => cb.value);
    const start_date = document.getElementById('compare-start').value;
    const end_date = document.getElementById('compare-end').value;
    const include_community_avg = document.getElementById('compare-community-avg')?.checked || false;
    const include_persona_avg = document.getElementById('compare-persona-avg')?.checked || false;
    const period_over_period = document.getElementById('compare-prev-period')?.checked || false;

    if (!entity_ids.length || !metrics.length) {
      toast('Please select at least one target and one metric.', 'error');
      return;
    }

    const btn = document.getElementById('btn-run-compare');
    btn.textContent = 'Running...';
    btn.disabled = true;

    try {
      const res = await api('/api/admin/analytics/compare', {
        method: 'POST',
        body: JSON.stringify({ entity_type, entity_ids, start_date, end_date, metrics, include_community_avg, include_persona_avg, period_over_period })
      });
      _lastComparisonData = { datasets: res.datasets, metrics };
      renderComparisonChart(res.datasets, metrics);
    } catch (err) {
      toast('Comparison failed: ' + err.message, 'error');
    } finally {
      btn.textContent = 'Compare';
      btn.disabled = false;
    }
  });

  document.getElementById('btn-compare-export').addEventListener('click', () => {
    if (!_lastComparisonData) {
      toast('No data to export. Run a comparison first.', 'error');
      return;
    }
    const { datasets, metrics } = _lastComparisonData;
    
    const dateSet = new Set();
    datasets.forEach(ds => ds.data.forEach(d => dateSet.add(d.date)));
    const labels = Array.from(dateSet).sort();

    let csvContent = 'Date,' + datasets.map(ds => metrics.map(m => `"${ds.entity_name} - ${m}"`).join(',')).join(',') + '\n';
    
    labels.forEach(date => {
      let row = [date];
      datasets.forEach(ds => {
        const pt = ds.data.find(d => d.date === date);
        metrics.forEach(m => {
          row.push(pt && pt[m] !== undefined ? pt[m] : '');
        });
      });
      csvContent += row.join(',') + '\n';
    });
    
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.setAttribute('download', 'advanced_comparison_export.csv');
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  });

  document.getElementById('btn-compare-alert').addEventListener('click', () => {
    if (!_lastComparisonData || !_lastComparisonData.datasets.length) {
      toast('No data to evaluate. Run a comparison first.', 'error');
      return;
    }
    const typeSelect = document.getElementById('compare-entity-type').value;
    let userIds = [];
    if (typeSelect === 'user') {
      userIds = _lastComparisonData.datasets.map(d => d.entity_id);
    } else {
      userIds = _lastComparisonData.datasets.map(d => d.target_user_id).filter(Boolean);
    }
    const uniqueUserIds = [...new Set(userIds)];
    
    if (!uniqueUserIds.length) {
      toast('Could not resolve user targets for the selected items.', 'error');
      return;
    }

    // Navigate and Pre-fill Notification Modal
    navigateTo('notifications');
    const targetSelect = document.getElementById('notif-target');
    targetSelect.value = 'specific';
    targetSelect.dispatchEvent(new Event('change')); // Trigger display of extra input
    document.getElementById('notif-user-ids').value = uniqueUserIds.join(', ');
    document.getElementById('notif-title').value = "Anomaly Detected in your Energy Profile";
    document.getElementById('notif-message').value = "We noticed abnormal energy signatures from your recent comparison records. Please check your appliance cycles.";
    
    // Scroll to the notification form
    document.getElementById('notif-form').scrollIntoView({ behavior: 'smooth' });
  });
}

function renderComparisonChart(datasets, metrics) {
  destroyChart('chart-advanced-compare');
  const ctx = document.getElementById('chart-advanced-compare')?.getContext('2d');
  if (!ctx) return;

  if (!datasets || !datasets.length || datasets.every(ds => !ds.data.length)) {
    toast('No comparative data found for the selected range.', 'info');
    return;
  }

  // Extract all unique dates to form the x-axis
  const dateSet = new Set();
  datasets.forEach(ds => ds.data.forEach(d => dateSet.add(d.date)));
  const labels = Array.from(dateSet).sort();

  const chartDatasets = [];
  const colors = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ef4444', '#14b8a6', '#f43f5e'];

  datasets.forEach((ds, dsIndex) => {
    const color = colors[dsIndex % colors.length];
    
    metrics.forEach((metric, mIndex) => {
      // Map data aligned to labels
      const dataAligned = labels.map(label => {
        const point = ds.data.find(d => d.date === label);
        return point ? point[metric] : null;
      });

      const isDashed = mIndex > 0;
      
      chartDatasets.push({
        label: `${ds.entity_name} - ${metric}`,
        data: dataAligned,
        borderColor: color,
        backgroundColor: color + '20',
        borderDash: isDashed ? [5, 5] : [],
        tension: 0.3,
        fill: false,
        spanGaps: true
      });
    });
  });

  _charts['chart-advanced-compare'] = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets: chartDatasets },
    options: {
      responsive: true,
      interaction: { mode: 'index', intersect: false },
      plugins: { legend: { labels: { color: '#94a3b8', font: { size: 12 } } } },
      scales: {
        x: { ticks: { color: '#6b7280' }, grid: { color: 'rgba(255,255,255,0.05)' } },
        y: { ticks: { color: '#6b7280' }, grid: { color: 'rgba(255,255,255,0.05)' } },
      },
    },
  });
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
      <div class="device-stat" style="color:var(--success)"><strong>${online}</strong> online (last 15 min)</div>
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
        <td><button class="btn-sm btn-danger" onclick="adminDeleteDevice(${d.device_id})">Delete</button></td>
      </tr>`).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" class="loading-row">Error: ${DOMPurify.sanitize(err.message)}</td></tr>`;
    toast('Device status load failed', 'error');
  }
}

async function adminDeleteDevice(deviceId) {
  if (!confirm('Are you sure you want to delete this device?')) return;
  try {
    await api(`/api/admin/devices/${deviceId}`, { method: 'DELETE' });
    toast('Device deleted successfully', 'success');
    loadDevices();
  } catch (err) { toast('Delete failed: ' + err.message, 'error'); }
}

// ── Notifications ─────────────────────────────────────────────
async function loadTemplates() {
  const el = document.getElementById('template-list');
  el.innerHTML = '<div class="loading-row">Loading…</div>';
  try {
    const templates = await api('/api/admin/notifications/templates');
    if (!templates?.length) { el.innerHTML = '<div class="loading-row">No templates yet</div>'; return; }
    el.innerHTML = '';
    templates.forEach(t => {
      const item = document.createElement('div');
      item.className = 'template-item';
      item.innerHTML = '<div class="template-item-title"></div><div class="template-item-type"></div>';
      item.querySelector('.template-item-title').textContent = t.name;
      item.querySelector('.template-item-type').textContent =
        `${t.notification_type} · ${t.severity}${t.requires_user_action ? ' · asks for response' : ''}`;
      item.addEventListener('click', () => applyTemplate(t));
      el.appendChild(item);
    });
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
  const req = document.getElementById('notif-requires-action');
  req.checked = !!t.requires_user_action;
  document.getElementById('notif-action-fields').style.display = req.checked ? 'block' : 'none';
  document.getElementById('notif-action-hint').value = t.action_hint || '';
  document.getElementById('notif-button-text').value = t.action_button_text || '';
  toast('Template applied', 'info');
}

// ── Backups ───────────────────────────────────────────────────
async function loadBackups() {
  const el = document.getElementById('backup-list');
  el.innerHTML = '<div class="loading-row">Loading…</div>';
  try {
    // GET /api/admin/backup/list returns an array of {name, size_mb, created_at}
    const backups = (await api('/api/admin/backup/list')) || [];
    if (!backups.length) { el.innerHTML = '<div class="loading-row">No scheduled backups yet (the nightly job writes one every 24 h)</div>'; }
    else {
      el.innerHTML = '';
      backups.forEach(b => {
        const row = document.createElement('div');
        row.className = 'backup-entry';
        row.innerHTML = '<div class="backup-icon">💾</div><div class="backup-info"><div class="backup-filename"></div><div class="backup-meta"></div></div>';
        row.querySelector('.backup-filename').textContent = b.name;
        row.querySelector('.backup-meta').textContent =
          `${b.size_mb} MB · ${b.created_at ? new Date(b.created_at).toLocaleString('en-GB') : ''}`;
        el.appendChild(row);
      });
    }
  } catch (err) { el.innerHTML = '<div class="loading-row">Error loading backups</div>'; }
  populateExportUsers();
}

// Streams a fresh mysqldump from GET /api/admin/backup/download and saves it.
async function downloadFreshBackup() {
  const res = await fetch(`${API_BASE}/api/admin/backup/download`, { headers: { 'Authorization': `Bearer ${_token}` } });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  const blob = await res.blob();
  const name = (res.headers.get('Content-Disposition') || '').match(/filename="?([^"]+)"?/)?.[1] || 'wattwise-backup.sql.gz';
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
}

// ── Participant data export ───────────────────────────────────
async function populateExportUsers() {
  const sel = document.getElementById('export-user-select');
  if (!sel) return;
  try {
    const users = await api('/api/admin/users?limit=1000');
    sel.innerHTML = (users || []).map(u =>
      `<option value="${u.id}">${DOMPurify.sanitize(u.name)} — ${DOMPurify.sanitize(u.email || '')}</option>`).join('');
  } catch (err) { console.warn('export users:', err.message); }
}

async function exportSelectedUsers() {
  const sel = document.getElementById('export-user-select');
  const ids = Array.from(sel?.selectedOptions || []).map(o => parseInt(o.value));
  if (!ids.length) { toast('Select at least one participant', 'error'); return; }
  const days = parseInt(document.getElementById('export-days')?.value || '90');
  try {
    let data, fname;
    if (ids.length === 1) {
      data = await api(`/api/admin/export/user/${ids[0]}?days=${days}`);
      fname = `wattwise-user-${ids[0]}.json`;
    } else {
      data = await api('/api/admin/export/users', { method: 'POST', body: JSON.stringify({ user_ids: ids, days }) });
      fname = `wattwise-users-${ids.length}.json`;
    }
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = fname;
    a.click();
    URL.revokeObjectURL(a.href);
    toast(`Exported ${ids.length} participant(s)`, 'success');
  } catch (err) { toast('Export failed: ' + err.message, 'error'); }
}

// ── Pipeline health strip (dashboard) ─────────────────────────
async function loadPipelineHealth() {
  const el = document.getElementById('pipeline-health');
  if (!el) return;
  try {
    const h = await api('/api/admin/system/pipeline-health');
    const fmtAge = m => m == null ? 'never' : (m < 60 ? `${Math.round(m)}m ago` : `${(m / 60).toFixed(1)}h ago`);
    const stages = [
      ['Ingest', h.ingest], ['Hourly agg', h.hourly_agg], ['Daily agg', h.daily_agg],
      ['Rankings', h.rankings], ['Personas', h.persona_run],
    ];
    el.innerHTML = stages.map(([name, s]) =>
      `<span title="${s.at || 'no data'}"><span style="color:${s.stale ? '#ef4444' : '#10b981'}">●</span> ${name}: ${fmtAge(s.age_min)}</span>`
    ).join('') + `<span style="opacity:.7">· ${(h.total_readings || 0).toLocaleString()} readings</span>`;
  } catch (err) { el.textContent = 'unavailable'; }
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
let _rankingsAvailableDates = [];

function _formatRankingsRange(meta) {
  if (!meta) return '';
  const fmt = (s) => new Date(s + 'T00:00:00').toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
  if (meta.period_type === 'DAILY') return `${fmt(meta.period_start)} · ${meta.row_count} homes ranked`;
  if (meta.period_type === 'WEEKLY') return `Week of ${fmt(meta.period_start)} → ${fmt(meta.period_end)} · ${meta.row_count} homes ranked`;
  // MONTHLY
  const d = new Date(meta.period_start + 'T00:00:00');
  return `${d.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })} · ${meta.row_count} homes ranked`;
}

function _populateRankingsDateDropdown(dates, currentValue) {
  const sel = document.getElementById('rankings-date-select');
  if (!sel) return;
  const fmt = (s) => new Date(s + 'T00:00:00').toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
  if (!dates.length) {
    sel.innerHTML = '<option value="">no periods available</option>';
    return;
  }
  sel.innerHTML = dates.map(d => `<option value="${d}">${fmt(d)}</option>`).join('');
  if (currentValue && dates.includes(currentValue)) sel.value = currentValue;
}

async function loadRankings(targetDate = null) {
  const period = document.getElementById('rankings-period')?.value || 'DAILY';
  const tbody = document.getElementById('rankings-tbody');
  const titleEl = document.getElementById('rankings-title');
  const metaEl = document.getElementById('rankings-meta');
  tbody.innerHTML = '<tr><td colspan="9" class="loading-row">Loading…</td></tr>';

  try {
    let url = `/api/admin/rankings?period=${period}`;
    if (targetDate) url += `&date_str=${targetDate}`;
    const resp = await api(url);
    const meta = resp?.meta || {};
    const rows = resp?.rankings || [];

    _rankingsAvailableDates = meta.available_period_starts || [];
    _populateRankingsDateDropdown(_rankingsAvailableDates, meta.period_start);

    if (titleEl) titleEl.textContent = `Community Rankings (${period.charAt(0) + period.slice(1).toLowerCase()})`;
    if (metaEl) metaEl.textContent = _formatRankingsRange(meta) || 'No data for selected period';

    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="9" class="loading-row">No data for selected period — click ⚙ Recompute or select another date</td></tr>';
      return;
    }

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
        <td>${r.percentile != null ? `${r.percentile.toFixed(0)}th` : '—'}</td>
      </tr>`).join('');
  } catch (err) { toast('Rankings load failed: ' + err.message, 'error'); }
}

function _stepRanking(direction) {
  // direction = -1 (older) or +1 (newer); the dates array is sorted DESC (newest first)
  const sel = document.getElementById('rankings-date-select');
  if (!sel || !_rankingsAvailableDates.length) return;
  const idx = _rankingsAvailableDates.indexOf(sel.value);
  // If older (-1), move to next index in descending list (further back in time = idx + 1)
  // If newer (+1), move to previous index (idx - 1)
  const target = direction === -1 ? idx + 1 : idx - 1;
  if (target >= 0 && target < _rankingsAvailableDates.length) {
    sel.value = _rankingsAvailableDates[target];
    loadRankings(_rankingsAvailableDates[target]);
  }
}

// ── Initialisation ────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', async () => {
  if (!await checkAuth()) return;
  initDecisionsUi();
  initHomesUi();

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

  // Theme Toggle
  const themeBtn = document.getElementById('btn-theme-toggle');
  const initTheme = () => {
    if (localStorage.getItem('wattwise_admin_theme') === 'light') {
      document.body.classList.add('light-mode');
      themeBtn.textContent = '🌙';
    } else {
      document.body.classList.remove('light-mode');
      themeBtn.textContent = '☀️';
    }
  };
  initTheme();
  themeBtn.addEventListener('click', () => {
    const isLight = document.body.classList.toggle('light-mode');
    localStorage.setItem('wattwise_admin_theme', isLight ? 'light' : 'dark');
    themeBtn.textContent = isLight ? '🌙' : '☀️';
  });

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
  document.getElementById('persona-history-period')?.addEventListener('change', loadPersonaHistoryChart);
  document.getElementById('persona-history-buckets')?.addEventListener('change', loadPersonaHistoryChart);
  document.getElementById('btn-close-persona-members')?.addEventListener('click', () => {
    document.getElementById('persona-members-card').style.display = 'none';
  });

  // Rankings
  document.getElementById('rankings-period')?.addEventListener('change', () => loadRankings());
  document.getElementById('rankings-date-select')?.addEventListener('change', (e) => loadRankings(e.target.value));
  document.getElementById('btn-rankings-prev')?.addEventListener('click', () => _stepRanking(-1));
  document.getElementById('btn-rankings-next')?.addEventListener('click', () => _stepRanking(+1));
  document.getElementById('btn-rankings-latest')?.addEventListener('click', () => loadRankings());
  document.getElementById('btn-rankings-recompute')?.addEventListener('click', async () => {
    const period = document.getElementById('rankings-period')?.value || 'ALL';
    if (!confirm(`Recompute ${period} rankings over full history? This rewrites the rankings table.`)) return;
    toast('Recomputing rankings…', 'info');
    try {
      const res = await api(`/api/admin/rankings/recompute?period=${period}`, { method: 'POST' });
      toast(`Recomputed: ${JSON.stringify(res.counts)}`, 'success');
      await loadRankings();
    } catch (err) { toast('Recompute failed: ' + err.message, 'error'); }
  });
  document.getElementById('ranking-period-select').addEventListener('change', loadTopRankings);

  // Devices
  document.getElementById('btn-refresh-devices').addEventListener('click', loadDevices);

  // Energy period dropdown — refresh the community chart on change
  document.getElementById('energy-period-select')?.addEventListener('change', () => loadDashboard());

  // Notification breakdown refresh
  document.getElementById('btn-refresh-notif-breakdown')?.addEventListener('click', loadNotifBreakdown);

  // Decision simulator
  document.getElementById('btn-simulate-decisions')?.addEventListener('click', runDecisionsSimulator);

  // Anomaly scan trigger
  document.getElementById('btn-anomaly-scan')?.addEventListener('click', async () => {
    const fb = document.getElementById('smart-notif-feedback');
    fb.textContent = 'Scanning anomalies…';
    fb.className = 'form-feedback';
    try {
      const res = await api('/api/admin/anomalies/scan?threshold_factor=3.0&lookback_hours=48', { method: 'POST' });
      fb.textContent = `✅ Anomaly scan: ${res.created} new notifications, ${res.skipped_dedup} skipped (dedup), threshold ${res.threshold_factor}×`;
      fb.className = 'form-feedback success';
    } catch (err) {
      fb.textContent = `❌ ${err.message}`;
      fb.className = 'form-feedback error';
    }
  });

  // MQTT broker stats
  document.getElementById('btn-refresh-mqtt-stats')?.addEventListener('click', loadMqttBrokerStats);

  // Anomaly toggle on live device chart
  document.getElementById('device-ts-anomalies')?.addEventListener('change', () => loadDeviceTimeseries());

  // CSV exports
  document.getElementById('btn-export-energy')?.addEventListener('click', async () => {
    const period = _energyPeriodQuery();
    try {
      const rows = await api(`/api/admin/analytics/energy?${period.query}`);
      if (!rows?.length) { toast('No data to export', 'info'); return; }
      downloadCsv(
        `wattwise-community-energy-${period.query.replace('=', '-')}.csv`,
        ['date', 'total_kwh', 'total_cost_gbp', 'avg_home_kwh', 'active_homes'],
        rows.map(r => [r.date, r.total_kwh, r.total_cost_gbp, r.avg_home_kwh, r.active_homes]),
      );
      toast('CSV downloaded', 'success');
    } catch (err) { toast('Export failed: ' + err.message, 'error'); }
  });

  document.getElementById('btn-export-rankings')?.addEventListener('click', async () => {
    const period = document.getElementById('rankings-period')?.value || 'DAILY';
    const date = document.getElementById('rankings-date-select')?.value || '';
    try {
      let url = `/api/admin/rankings?period=${period}`;
      if (date) url += `&date_str=${date}`;
      const resp = await api(url);
      const rows = resp?.rankings || [];
      if (!rows.length) { toast('No data to export', 'info'); return; }
      downloadCsv(
        `wattwise-rankings-${period.toLowerCase()}-${resp.meta.period_start}.csv`,
        ['rank', 'home', 'user', 'score', 'efficiency', 'goal_adherence', 'total_kwh', 'cost_gbp', 'percentile'],
        rows.map(r => [r.rank, r.home, r.user_name, r.score, r.efficiency, r.goal_adherence, r.total_kwh, r.cost_gbp, r.percentile]),
      );
      toast('CSV downloaded', 'success');
    } catch (err) { toast('Export failed: ' + err.message, 'error'); }
  });

  document.getElementById('btn-export-device-ts')?.addEventListener('click', async () => {
    const hours = parseInt(document.getElementById('device-ts-period')?.value || '24', 10);
    const homeId = document.getElementById('device-ts-home')?.value || '';
    try {
      let url = `/api/admin/analytics/device-timeseries?hours=${hours}`;
      if (homeId) url += `&home_id=${encodeURIComponent(homeId)}`;
      const data = await api(url);
      const devices = data?.devices || [];
      if (!devices.length) { toast('No data to export', 'info'); return; }
      const rows = [];
      devices.forEach(d => {
        d.points.forEach(p => {
          rows.push([d.home_name, d.device_name, d.appliance_key, p.ts, p.kwh, p.avg_watts]);
        });
      });
      downloadCsv(
        `wattwise-device-telemetry-${hours}h.csv`,
        ['home', 'device', 'appliance', 'hour_start', 'kwh', 'avg_watts'],
        rows,
      );
      toast(`CSV downloaded — ${rows.length} rows`, 'success');
    } catch (err) { toast('Export failed: ' + err.message, 'error'); }
  });

  // Live device telemetry controls
  document.getElementById('device-ts-period')?.addEventListener('change', () => loadDeviceTimeseries());
  document.getElementById('device-ts-home')?.addEventListener('change', () => loadDeviceTimeseries());

  // Kick off the 30-second auto-refresh for the live device chart
  startDeviceTimeseriesAutoRefresh();
  // Kick off the 10-second auto-refresh for the MQTT broker panel
  startMqttBrokerAutoRefresh();

  // Dashboard auto-refresh (10 s) + Analytics auto-refresh (60 s). Only fire when the
  // relevant tab is active and the window is visible — no wasted polling on hidden tabs.
  setInterval(() => {
    if (!document.hidden && document.getElementById('section-dashboard')?.classList.contains('active')) loadDashboard();
  }, 10000);
  setInterval(() => {
    if (!document.hidden && document.getElementById('section-analytics')?.classList.contains('active')) loadAnalytics();
  }, 60000);

  // Notifications form
  document.getElementById('notif-form').addEventListener('submit', async e => {
    e.preventDefault();
    const feedback = document.getElementById('notif-feedback');
    feedback.textContent = 'Sending…';
    feedback.className = 'form-feedback';
    try {
      const target = document.getElementById('notif-target').value;
      const ids = (document.getElementById('notif-user-ids')?.value || '')
        .split(',').map(x => parseInt(x.trim(), 10)).filter(n => !isNaN(n));
      if ((target === 'specific' || target === 'homes') && !ids.length) throw new Error('Enter at least one ID');
      const personaId = target === 'persona' ? parseInt(document.getElementById('notif-persona-id')?.value || '0', 10) : null;
      const requiresAction = document.getElementById('notif-requires-action').checked;
      const sendAtLocal = document.getElementById('notif-send-at').value;

      const res = await api('/api/admin/notifications/send', {
        method: 'POST',
        body: JSON.stringify({
          title: document.getElementById('notif-title').value,
          message: document.getElementById('notif-message').value,
          notification_type: document.getElementById('notif-type').value,
          severity: document.getElementById('notif-severity').value,
          user_ids: target === 'specific' ? ids : null,
          home_ids: target === 'homes' ? ids : null,
          target_persona_id: personaId || null,
          cohort: ['real', 'synthetic'].includes(target) ? target : 'all',
          requires_user_action: requiresAction,
          action_hint: requiresAction ? (document.getElementById('notif-action-hint').value.trim() || null) : null,
          action_button_text: requiresAction ? (document.getElementById('notif-button-text').value.trim() || null) : null,
          appliance_key: requiresAction ? (document.getElementById('notif-appliance').value || null) : null,
          // The API stores UTC; the picker gives local time.
          send_at: sendAtLocal ? new Date(sendAtLocal).toISOString().slice(0, 19) : null,
        }),
      });
      feedback.textContent = res.status === 'SCHEDULED'
        ? `🕒 Scheduled for ${fmtWhen(res.send_at)} — see the Decisions tab to cancel`
        : `✅ Delivered to ${res.notifications_created} of ${res.recipients_targeted} targeted user(s). Responses appear in the Decisions tab.`;
      feedback.className = 'form-feedback success';
    } catch (err) {
      feedback.textContent = `❌ ${err.message}`;
      feedback.className = 'form-feedback error';
    }
  });
  document.getElementById('notif-target').addEventListener('change', async e => {
    const extra = document.getElementById('notif-target-extra');
    const personaWrap = document.getElementById('notif-target-persona');
    extra.style.display = ['specific', 'homes'].includes(e.target.value) ? 'block' : 'none';
    document.getElementById('notif-user-ids').placeholder =
      e.target.value === 'homes' ? 'Comma-separated home IDs…' : 'Comma-separated user IDs…';
    personaWrap.style.display = e.target.value === 'persona' ? 'block' : 'none';
    if (e.target.value === 'persona') {
      try {
        const personas = await api('/api/admin/personas');
        document.getElementById('notif-persona-id').innerHTML = (personas || [])
          .map(p => `<option value="${p.id}">${DOMPurify.sanitize(p.name)} (${p.user_count} users)</option>`)
          .join('');
      } catch {}
    }
  });
  document.getElementById('btn-refresh-templates').addEventListener('click', loadTemplates);
  document.getElementById('btn-smart-notif-all').addEventListener('click', async () => {
    const fb = document.getElementById('smart-notif-feedback');
    fb.textContent = 'Running smart notifications…';
    fb.className = 'form-feedback';
    try {
      const res = await api('/api/admin/trigger-smart-notifications-all', { method: 'POST' });
      fb.textContent = `✅ Smart notifications done: ${res.notifications_created} new, ${res.skipped_dedup} skipped (dedup), ${res.users_processed} users processed`;
      fb.className = 'form-feedback success';
    } catch (err) {
      fb.textContent = `❌ ${err.message}`;
      fb.className = 'form-feedback error';
    }
  });

  // Backup
  document.getElementById('btn-trigger-backup').addEventListener('click', async () => {
    try {
      toast('Creating backup…', 'info');
      await downloadFreshBackup();
      toast('Backup downloaded', 'success');
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
  // Null-safe: one missing input here used to throw and silently skip everything
  // below it — including initAdvancedComparison(), which left the comparison tool dead.
  const setValue = (id, v) => { const el = document.getElementById(id); if (el) el.value = v; };
  setValue('analytics-start', week);
  setValue('analytics-end', today);
  setValue('rankings-date', new Date(Date.now() - 86400000).toISOString().slice(0,10));

  // Initialize Advanced Comparison UI
  initAdvancedComparison();

  // Load initial section
  navigateTo('dashboard');

  // Sankey + anomaly trigger wiring
  document.getElementById('sankey-days')?.addEventListener('change', loadSankey);
  document.getElementById('sankey-top-homes')?.addEventListener('change', loadSankey);
  document.getElementById('btn-sankey-refresh')?.addEventListener('click', loadSankey);

  // Expose to onclick handlers
  window.openUserPanel = openUserPanel;
  window.toggleUserNotif = toggleUserNotif;
  window.closeUserPanel = closeUserPanel;
  window.adminResetPassword = adminResetPassword;
  window.sendUserNotif = sendUserNotif;
  window.filterUsersByPersona = filterUsersByPersona;
  window.applyTemplate = applyTemplate;
  window.toggleUserDrill = toggleUserDrill;
});

// ── Sankey: Energy Flow ────────────────────────────────────────
async function loadSankey() {
  const container = document.getElementById('sankey-container');
  const summaryEl = document.getElementById('sankey-summary');
  const titleEl = document.getElementById('sankey-title');
  if (!container) return;

  if (typeof d3 === 'undefined' || !d3.sankey) {
    container.innerHTML = '<div class="loading-row">D3-Sankey library failed to load (offline?)</div>';
    return;
  }

  const days = parseInt(document.getElementById('sankey-days')?.value || '7', 10);
  const topHomes = parseInt(document.getElementById('sankey-top-homes')?.value || '10', 10);
  if (titleEl) titleEl.textContent = `Energy Flow Sankey (last ${days === 1 ? '24h' : days + ' days'})`;
  container.innerHTML = '<div class="loading-row">Loading…</div>';

  try {
    const data = await api(`/api/admin/analytics/sankey?days=${days}&top_homes=${topHomes}`);
    if (!data.nodes?.length) {
      container.innerHTML = '<div class="loading-row">No data in this window</div>';
      summaryEl.textContent = '';
      return;
    }

    container.innerHTML = '';

    const width = container.clientWidth - 28;
    const height = Math.max(380, data.nodes.length * 16);

    const svg = d3.select(container)
      .append('svg')
      .attr('width', width)
      .attr('height', height)
      .style('font', '11px Inter, sans-serif');

    // Map node objects + links by name
    const idIndex = new Map(data.nodes.map((n, i) => [n.id, i]));
    const sankeyData = {
      nodes: data.nodes.map(n => ({ ...n })),
      links: data.links.map(l => ({
        source: idIndex.get(l.source),
        target: idIndex.get(l.target),
        value: l.value,
      })),
    };

    const sankey = d3.sankey()
      .nodeWidth(14)
      .nodePadding(8)
      .extent([[1, 1], [width - 1, height - 6]]);

    const graph = sankey(sankeyData);

    const colour = (d) => {
      if (d.layer === 0) return '#3b82f6';     // homes
      if (d.layer === 1) return '#10b981';     // appliances
      return '#f59e0b';                         // time buckets
    };

    // Links
    svg.append('g')
      .selectAll('path')
      .data(graph.links)
      .join('path')
      .attr('d', d3.sankeyLinkHorizontal())
      .attr('fill', 'none')
      .attr('stroke', d => colour(d.source))
      .attr('stroke-width', d => Math.max(1, d.width))
      .attr('stroke-opacity', 0.35)
      .append('title')
      .text(d => `${d.source.id} → ${d.target.id}\n${d.value.toFixed(2)} kWh`);

    // Nodes
    const node = svg.append('g')
      .selectAll('g')
      .data(graph.nodes)
      .join('g');

    node.append('rect')
      .attr('x', d => d.x0)
      .attr('y', d => d.y0)
      .attr('height', d => d.y1 - d.y0)
      .attr('width', d => d.x1 - d.x0)
      .attr('fill', colour)
      .append('title')
      .text(d => `${d.id}\n${(d.value || 0).toFixed(2)} kWh`);

    node.append('text')
      .attr('x', d => d.x0 < width / 2 ? d.x1 + 6 : d.x0 - 6)
      .attr('y', d => (d.y0 + d.y1) / 2)
      .attr('dy', '0.35em')
      .attr('text-anchor', d => d.x0 < width / 2 ? 'start' : 'end')
      .style('fill', '#cbd5e1')
      .style('font-size', '10px')
      .text(d => d.id.length > 28 ? d.id.slice(0, 26) + '…' : d.id);

    summaryEl.textContent = `${data.node_count} nodes · ${data.link_count} links · total ${data.total_kwh.toLocaleString()} kWh in window`;
  } catch (err) {
    container.innerHTML = `<div class="loading-row">Failed: ${h(err.message)}</div>`;
    console.warn('Sankey:', err.message);
  }
}

// ── Per-user admin drill-down (Hourly profile + Standby) ──────
async function toggleUserDrill(userId, userName, btnEl) {
  const rowEl = btnEl?.closest('tr');
  if (!rowEl) return;

  // If a drill row already exists right after, remove it (toggle close)
  const next = rowEl.nextElementSibling;
  if (next && next.classList.contains('user-drill-row')) {
    next.remove();
    return;
  }

  // Insert a new drill row beneath this user row
  const drill = document.createElement('tr');
  drill.className = 'user-drill-row';
  const colCount = rowEl.children.length;
  drill.innerHTML = `<td colspan="${colCount}" style="padding:0;background:rgba(255,255,255,0.02)">
    <div id="user-drill-${userId}" style="padding:14px 18px">
      <div class="loading-row">Loading insights for ${DOMPurify.sanitize(userName || 'user')}…</div>
    </div>
  </td>`;
  rowEl.parentNode.insertBefore(drill, next);

  try {
    // Use the per-user details endpoint for headline stats
    const det = await api(`/api/admin/users/${userId}/details`).catch(() => null);
    const homes = det?.homes || [];
    const allDevices = homes.flatMap(h => (h.devices || []).map(d => ({ ...d, home_name: h.home_name })));

    if (!allDevices.length) {
      document.getElementById(`user-drill-${userId}`).innerHTML =
        '<div class="loading-row">No devices registered for this user</div>';
      return;
    }

    // Pick the most-active device (or just the first)
    const targetDevice = allDevices[0];

    const [profile, standby] = await Promise.all([
      api(`/api/readings/${targetDevice.id}/hourly-profile?days=14`).catch(() => null),
      api(`/api/readings/${targetDevice.id}/standby?days=14`).catch(() => null),
    ]);

    const summaryHtml = profile ? `
      <div style="font-size:12px;color:#94a3b8;margin-bottom:8px">
        14-day avg: ${profile.summary.avg_daily_kwh} kWh/day ·
        ${profile.summary.peak_tariff_kwh_share_pct}% in peak tariff
      </div>
    ` : '';

    const standbyHtml = standby ? (() => {
      const colour = standby.severity === 'critical' ? '#ef4444'
                  : standby.severity === 'warning'  ? '#f59e0b' : '#10b981';
      return `
        <div style="border-left:3px solid ${colour};padding:8px 12px;margin-top:8px;background:rgba(255,255,255,0.02);border-radius:6px">
          <div style="font-weight:600;font-size:13px">Standby: ${(standby.standby_kwh || 0).toFixed(3)} kWh
            (${(standby.standby_share_pct || 0).toFixed(1)}% of total)</div>
          <div style="font-size:11px;color:#94a3b8;margin-top:2px">
            Annualised: ${(standby.annualised_standby_kwh || 0).toFixed(1)} kWh / £${(standby.annualised_standby_cost_gbp || 0).toFixed(2)}
            — ${DOMPurify.sanitize(standby.advice || '')}
          </div>
        </div>
      `;
    })() : '';

    const deviceSelector = allDevices.length > 1 ? `
      <select id="udrill-device-${userId}" class="select-sm" style="margin-bottom:10px">
        ${allDevices.map(d => `<option value="${d.id}">${DOMPurify.sanitize(d.home_name)} · ${DOMPurify.sanitize(d.name)}</option>`).join('')}
      </select>
    ` : `<div style="font-size:12px;color:#94a3b8;margin-bottom:8px">${DOMPurify.sanitize(targetDevice.home_name)} · ${DOMPurify.sanitize(targetDevice.name)}</div>`;

    document.getElementById(`user-drill-${userId}`).innerHTML = `
      ${deviceSelector}
      <div class="card-title" style="font-size:13px;margin-bottom:6px">⏰ Hourly Profile (14 days)</div>
      ${summaryHtml}
      <canvas id="udrill-canvas-${userId}" height="80"></canvas>
      ${standbyHtml}
    `;

    if (profile) _renderUserDrillProfile(userId, profile);

    // Wire device selector to reload chart for selected device
    const sel = document.getElementById(`udrill-device-${userId}`);
    if (sel) {
      sel.addEventListener('change', async (e) => {
        const newId = parseInt(e.target.value);
        const [p2, s2] = await Promise.all([
          api(`/api/readings/${newId}/hourly-profile?days=14`).catch(() => null),
          api(`/api/readings/${newId}/standby?days=14`).catch(() => null),
        ]);
        if (p2) _renderUserDrillProfile(userId, p2);
        // Note: standby panel re-render skipped for brevity; user can close + reopen
      });
    }
  } catch (err) {
    document.getElementById(`user-drill-${userId}`).innerHTML =
      `<div class="loading-row">Error loading insights: ${h(err.message)}</div>`;
  }
}

function _renderUserDrillProfile(userId, profile) {
  const ctx = document.getElementById(`udrill-canvas-${userId}`);
  if (!ctx) return;
  const chartId = `udrill-chart-${userId}`;
  destroyChart(chartId);
  _charts[chartId] = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: profile.profile.map(p => p.label),
      datasets: [{
        label: 'avg kWh/h',
        data: profile.profile.map(p => p.avg_kwh),
        backgroundColor: profile.profile.map(p =>
          p.is_personal_peak ? '#8b5cf6'
          : p.is_peak_tariff ? '#ef4444'
          : 'rgba(16,185,129,0.7)'),
        borderRadius: 3,
      }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: '#94a3b8', font: { size: 9 }, maxRotation: 0 }, grid: { display: false } },
        y: { ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.04)' } },
      },
    },
  });
}
