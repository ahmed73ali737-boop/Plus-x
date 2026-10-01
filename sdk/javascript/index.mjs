export class PulseXError extends Error {
  constructor(status, detail) {
    super(`PulseX API error ${status}: ${detail}`);
    this.status = status;
    this.detail = detail;
  }
}

export class PulseXClient {
  constructor({ baseUrl = '', fetchImpl = globalThis.fetch } = {}) {
    if (!fetchImpl) throw new Error('fetch implementation is required');
    this.baseUrl = baseUrl.replace(/\/$/, '');
    this.fetchImpl = fetchImpl;
    this.csrf = null;
  }

  async request(method, path, body) {
    const headers = { Accept: 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (this.csrf && ['POST','PUT','PATCH','DELETE'].includes(method)) headers['X-CSRF'] = this.csrf;
    const response = await this.fetchImpl(this.baseUrl + path, {
      method,
      headers,
      credentials: 'include',
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = response.status === 204 ? null : await response.json();
    if (!response.ok) throw new PulseXError(response.status, data?.detail ?? data);
    return data;
  }

  health() { return this.request('GET', '/api/health'); }
  async login(email, password) {
    const data = await this.request('POST', '/api/auth/login', { email, password });
    this.csrf = data.csrf;
    return data.user;
  }
  async me() {
    const data = await this.request('GET', '/api/auth/me');
    this.csrf = data.csrf ?? this.csrf;
    return data;
  }
  async logout() {
    const data = await this.request('POST', '/api/auth/logout', {});
    this.csrf = null;
    return data;
  }
  publicSite(slug) { return this.request('GET', `/api/public/site/${encodeURIComponent(slug)}`); }
  publicResults(slug) { return this.request('GET', `/api/public/site/${encodeURIComponent(slug)}/results`); }
  collect(items) { return this.request('POST', '/api/collect', { items }); }
  adminSites() { return this.request('GET', '/api/admin/sites'); }
  adminSite(id) { return this.request('GET', `/api/admin/sites/${encodeURIComponent(id)}`); }
  saveSite(id, draftRev, config) { return this.request('PUT', `/api/admin/sites/${encodeURIComponent(id)}`, { draft_rev: draftRev, config }); }
  publishSite(id, draftRev) { return this.request('POST', `/api/admin/sites/${encodeURIComponent(id)}/publish`, { draft_rev: draftRev }); }
  metrics(id) { return this.request('GET', `/api/admin/sites/${encodeURIComponent(id)}/metrics`); }
  organizations() { return this.request('GET', '/api/admin/organizations'); }
  devices(id) { return this.request('GET', `/api/admin/sites/${encodeURIComponent(id)}/devices`); }
  createDevice(id, name, deviceType, appVersion = '') { return this.request('POST', `/api/admin/sites/${encodeURIComponent(id)}/devices`, { name, device_type: deviceType, app_version: appVersion }); }
  updateDevice(id, deviceId, changes) { return this.request('PATCH', `/api/admin/sites/${encodeURIComponent(id)}/devices/${encodeURIComponent(deviceId)}`, changes); }
  reviewAccessRequest(id, requestId, status) { return this.request('PATCH', `/api/admin/sites/${encodeURIComponent(id)}/access-requests/${encodeURIComponent(requestId)}`, { status }); }
}

