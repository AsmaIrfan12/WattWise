/**
 * @typedef {Object} LoginResponse
 * @property {string} access_token
 * @property {boolean} is_admin
 *
 * @typedef {Object} AdminDashboardResponse
 * @property {number} total_users
 * @property {number} active_users_today
 * @property {number} total_homes
 * @property {number} total_devices
 * @property {number} energy_today_kwh
 * @property {number} cost_today_gbp
 * @property {number} notifications_sent_today
 * @property {number} decisions_recorded_today
 * @property {number} avg_goal_adherence_pct
 *
 * @typedef {Object} EnergyAnalyticsRow
 * @property {string} date
 * @property {number} total_kwh
 * @property {number} total_cost_gbp
 * @property {number} active_homes
 */

const API_BASE = "/api";

export class ApiError extends Error {
  /**
   * @param {string} message
   * @param {number} status
   */
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export class AdminApiClient {
  constructor() {
    this.token = localStorage.getItem("ww_token") || "";
  }

  /** @param {string} token */
  setToken(token) {
    this.token = token;
    localStorage.setItem("ww_token", token);
  }

  clearToken() {
    this.token = "";
    localStorage.removeItem("ww_token");
  }

  hasToken() {
    return Boolean(this.token);
  }

  /**
   * @template T
   * @param {string} path
   * @param {RequestInit} [opts]
   * @returns {Promise<T>}
   */
  async request(path, opts = {}) {
    const headers = {
      "Content-Type": "application/json",
      ...(opts.headers || {}),
    };

    if (this.token) {
      headers.Authorization = `Bearer ${this.token}`;
    }

    const response = await fetch(`${API_BASE}${path}`, {
      ...opts,
      headers,
    });

    if (!response.ok) {
      let message = `${response.status} ${response.statusText}`;
      try {
        const body = await response.json();
        if (Array.isArray(body?.detail)) {
          message = body.detail.map((d) => d.msg || JSON.stringify(d)).join(", ");
        } else if (body?.detail) {
          message = body.detail;
        }
      } catch {
        const text = await response.text().catch(() => "");
        if (text) {
          message = text;
        }
      }
      throw new ApiError(message, response.status);
    }

    return /** @type {Promise<T>} */ (response.json());
  }

  /** @param {{email: string, password: string}} payload @returns {Promise<LoginResponse>} */
  login(payload) {
    return this.request("/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  /** @returns {Promise<AdminDashboardResponse>} */
  getDashboard() {
    return this.request("/admin/dashboard");
  }

  /** @returns {Promise<Array<{name: string, email: string, last_login_at: string | null, notifications_enabled: boolean}>>} */
  getUsers() {
    return this.request("/admin/users");
  }

  /** @returns {Promise<Array<{rank: number, user_name: string, score: number, efficiency: number, goal_adherence: number, total_kwh: number, cost_gbp: number}>>} */
  getRankings() {
    return this.request("/admin/rankings?period=DAILY");
  }

  /** @param {number} days @returns {Promise<EnergyAnalyticsRow[]>} */
  getEnergyAnalytics(days) {
    return this.request(`/admin/analytics/energy?days=${days}`);
  }

  /** @returns {Promise<{has_data:boolean, date:string|null, registered_homes:number, homes_with_data:number, total_kwh:number, total_cost_gbp:number, avg_home_kwh:number, avg_home_cost_gbp:number, min_home_kwh:number, max_home_kwh:number, peer_homes_compared:number}>} */
  getCommunityBenchmark() {
    return this.request("/admin/analytics/community-benchmark");
  }

  /** @returns {Promise<{total_decisions: number, total_energy_saved_kwh: number, total_cost_saved_gbp: number, avg_effectiveness_score: number, accepted?: number, rejected?: number, avg_response_time_seconds?: number}>} */
  getDecisionAnalytics() {
    return this.request("/admin/analytics/decisions");
  }

  /**
   * @param {{title: string, message: string, severity: string, action_hint: string | null, requires_user_action: boolean, user_ids: number[] | null}} payload
   * @returns {Promise<{success: boolean, notifications_sent: number}>}
   */
  sendNotification(payload) {
    return this.request("/admin/notifications/send", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  /** @returns {Promise<{enabled: boolean, backup_count: number, last_backup_file: string|null, last_backup_size_mb: number|null, warning?: string}>} */
  getBackupSettings() {
    return this.request("/admin/backup/settings");
  }

  /** @param {{enabled: boolean}} payload @returns {Promise<{enabled: boolean, message: string}>} */
  setBackupSettings(payload) {
    return this.request("/admin/backup/settings", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  /** @returns {Promise<Array<{name: string, size_bytes: number, size_mb: number, created_at: string}>>} */
  listBackups() {
    return this.request("/admin/backup/list");
  }
}
