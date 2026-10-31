// Kept in memory only, so closing the page signs the person out.
let staffToken = null
let onSignedOut = () => {}

export function setStaffToken(token) {
  staffToken = token
}

export function setSignedOutHandler(handler) {
  onSignedOut = handler
}

async function request(path, options = {}) {
  const headers = { ...options.headers, ...(staffToken ? { Authorization: `Bearer ${staffToken}` } : {}) }
  let response
  try {
    response = await fetch(`/api${path}`, { ...options, headers })
  } catch {
    throw new Error("Can't reach Resolve. Is the backend running?")
  }
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    if (response.status === 401 && staffToken) {
      // The session ended, for example because the backend restarted.
      staffToken = null
      onSignedOut()
    }
    const error = new Error(body?.message ?? 'Something went wrong. Please try again.')
    error.status = response.status
    throw error
  }
  return body
}

function post(path, data) {
  return request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data ?? {}),
  })
}

export const api = {
  customers: () => request('/customers'),
  chat: (customerId, message, caseId) => post('/chat', { customer_id: customerId, message, case_id: caseId }),
  caseStatus: (caseId) => request(`/cases/${caseId}`),
  audit: (afterId) => request(`/audit?after=${afterId}`),
  tickets: () => request('/tickets'),
  approve: (ticketId) => post(`/tickets/${ticketId}/approve`),
  reject: (ticketId) => post(`/tickets/${ticketId}/reject`),
  simulateOutage: () => post('/outage/simulate'),
  scan: () => post('/scan'),
  incidents: () => request('/incidents'),
  approveIncident: (incidentId) => post(`/incidents/${incidentId}/approve`),
  holdIncident: (incidentId) => post(`/incidents/${incidentId}/hold`),
  notifications: (afterId) => request(`/notifications?after=${afterId}`),
  scoreboard: () => request('/scoreboard'),
  staffNames: () => request('/staff'),
  login: (name, pin) => post('/staff/login', { name, pin }),
}
