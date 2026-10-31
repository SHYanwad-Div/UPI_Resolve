import { useState } from 'react'
import { api } from '../api'
import { usePolling } from '../usePolling'

export default function ScoreBar({ staff, onSimulateAttacks }) {
  const [score, setScore] = useState(null)
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)

  usePolling(async () => setScore(await api.scoreboard()), 1500)

  async function run(action, call) {
    setBusy(action)
    setError(null)
    setNotice(null)
    try {
      const result = await call()
      if (action === 'scan') {
        const found = result.incidents.reduce((total, incident) => total + incident.total, 0)
        setNotice(found > 0 ? `Found ${found} stuck payments. See the card on the right.` : 'Nothing stuck right now.')
      }
    } catch (failure) {
      setError(failure.message)
    } finally {
      setBusy(null)
    }
  }

  const stats = [
    ['Resolved by AI', score?.auto_resolved ?? 0],
    ['Sent to humans', score?.escalated ?? 0],
    ['Avg. AI resolution', score?.average_seconds == null ? '–' : `${score.average_seconds}s`],
    ['Saved*', `₹${(score?.rupees_saved ?? 0).toLocaleString('en-IN')}`],
    ['Told before complaining', score?.told_first ?? 0],
    ['Attacks blocked', score?.attacks_blocked ?? 0],
  ]

  return (
    <section className="scorebar" aria-label="Scoreboard">
      <dl className="stats">
        {stats.map(([label, value]) => (
          <div key={label} className="stat">
            <dd>{value}</dd>
            <dt>{label}</dt>
          </div>
        ))}
      </dl>
      <div className="scorebar-actions">
        {error && (
          <span className="scorebar-error" role="alert">
            {error}
          </span>
        )}
        {notice && (
          <span className="scorebar-notice" role="status">
            {notice}
          </span>
        )}
        <button type="button" className="button button-outage" disabled={Boolean(busy) || !staff} title={staff ? undefined : 'Sign in as staff first'} onClick={() => run('outage', api.simulateOutage)}>
          {busy === 'outage' ? 'Handling outage...' : 'Simulate bank outage'}
        </button>
        <button type="button" className="button button-attack" disabled={Boolean(busy) || !staff} title={staff ? undefined : 'Sign in as staff first'} onClick={onSimulateAttacks}>
          Simulate attacks
        </button>
        <button type="button" className="button button-secondary" disabled={Boolean(busy) || !staff} title={staff ? undefined : 'Sign in as staff first'} onClick={() => run('scan', api.scan)}>
          {busy === 'scan' ? 'Scanning...' : 'Scan for stuck payments'}
        </button>
        <span className="scorebar-note">*Assumes ₹100 per human ticket, ₹10 per AI ticket</span>
      </div>
    </section>
  )
}
