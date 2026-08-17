async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.body && !(options.body instanceof Blob) ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {})
    }
  })
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      detail = body.detail || body.error || detail
    } catch {
      try { detail = await response.text() || detail } catch { /* noop */ }
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  const type = response.headers.get('content-type') || ''
  if (type.includes('application/json')) return response.json()
  return response.text()
}

const json = (method, body) => ({ method, body: JSON.stringify(body) })

export const api = {
  hostInfo: () => request('/api/host/info'),
  boards: () => request('/api/boards'),
  connect: (base_url, token) => request('/api/connection', json('POST', { base_url, token })),
  startConnect: (base_url, token) => request('/api/jobs/connect', json('POST', { base_url, token })),
  deviceInfo: () => request('/api/device/info'),
  auth: () => request('/api/device/auth'),
  status: () => request('/api/device/status'),
  setMode: (gpio, mode, force = false) => request(`/api/device/pins/${gpio}/mode`, json('POST', { mode, force })),
  writePin: (gpio, value) => request(`/api/device/pins/${gpio}/write`, json('POST', { value })),
  pwm: (gpio, duty_u16, frequency) => request(`/api/device/pins/${gpio}/pwm`, json('POST', { duty_u16, frequency })),
  files: (path = '/') => request(`/api/device/fs/list?path=${encodeURIComponent(path)}`),
  readFile: (path) => request(`/api/device/fs?path=${encodeURIComponent(path)}`),
  writeFile: (path, content, message = 'Save from Wi-Fi editor') => request('/api/device/fs', json('PUT', { path, content, message })),
  deleteFile: (path) => request(`/api/device/fs?path=${encodeURIComponent(path)}`, { method: 'DELETE' }),
  startSaveFile: (path, content, message = 'Save from Wi-Fi editor') => request('/api/jobs/fs-save', json('POST', { path, content, message })),
  startDeleteFile: (path) => request('/api/jobs/fs-delete', json('POST', { path })),
  wifi: (ssid, password) => request('/api/device/wifi', json('POST', { ssid, password })),
  reboot: () => request('/api/device/reboot', { method: 'POST' }),
  startWifi: (ssid, password) => request('/api/jobs/wifi', json('POST', { ssid, password })),
  startReboot: () => request('/api/jobs/reboot', { method: 'POST' }),

  ports: () => request('/api/serial/ports'),
  startProbe: (port) => request('/api/jobs/probe', json('POST', { port })),
  startFlash: (port, profile_id, erase = true, baud = 460800) => request('/api/jobs/flash', json('POST', { port, profile_id, erase, baud })),
  startInstall: (port, profile_id, ssid, password, token) => request('/api/jobs/install', json('POST', { port, profile_id, ssid, password, token })),
  startSerialFiles: (port) => request('/api/jobs/serial-files', json('POST', { port })),
  job: (jobId) => request(`/api/jobs/${encodeURIComponent(jobId)}`),

  history: (path = '', limit = 100) => request(`/api/history?${path ? `path=${encodeURIComponent(path)}&` : ''}limit=${limit}`),
  revision: (id) => request(`/api/history/${id}`),
  revisionDiff: (id) => request(`/api/history/${id}/diff`),
  restoreRevision: (id) => request(`/api/history/${id}/restore`, { method: 'POST' }),
  startRestoreRevision: (id) => request(`/api/jobs/history-restore/${encodeURIComponent(id)}`, { method: 'POST' }),
  startHistorySnapshot: (message = 'Manual project snapshot') => request('/api/jobs/history-snapshot', json('POST', { message })),

  cloudTokenStatus: (provider) => request(`/api/cloud/token-status?provider=${encodeURIComponent(provider)}`),
  cloudAuth: (provider, token, remember = false) => request('/api/cloud/auth', json('POST', { provider, token, remember })),
  startCloudAuth: (provider, token, remember = false) => request('/api/jobs/cloud-auth', json('POST', { provider, token, remember })),
  cloudForget: (provider) => request('/api/cloud/forget', json('POST', { provider, token: '', remember: false })),
  cloudScan: (scope = 'full') => request('/api/cloud/scan', json('POST', { scope })),
  startCloudScan: (scope = 'full') => request('/api/jobs/cloud-scan', json('POST', { scope })),
  cloudPublish: (provider, token, remember, repo_name, privateRepo, message, scope = 'full') => request('/api/cloud/publish', json('POST', {
    provider, token, remember, repo_name, private: privateRepo, message, scope
  })),

  activity: (scope = 'all', kind = 'all', source = 'all', limit = 250) => request(`/api/activity?scope=${encodeURIComponent(scope)}&kind=${encodeURIComponent(kind)}&source=${encodeURIComponent(source)}&limit=${limit}`),
  clearActivity: (scope = 'all', kind = 'all') => request(`/api/activity?scope=${encodeURIComponent(scope)}&kind=${encodeURIComponent(kind)}`, { method: 'DELETE' })
}
