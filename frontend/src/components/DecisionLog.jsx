import { useMemo, useRef, useState } from 'react'
import { api } from '../api'
import { usePolling } from '../usePolling'

const TIME_FORMAT = new Intl.DateTimeFormat('en-IN', {
  timeZone: 'Asia/Kolkata',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

function groupByCase(entries) {
  const cases = new Map()
  for (const entry of entries) {
    if (!cases.has(entry.case_id)) {
      cases.set(entry.case_id, { caseId: entry.case_id, customerName: entry.customer_name, steps: [] })
    }
    cases.get(entry.case_id).steps.push(entry)
  }
  // The most recently active case goes on top, even if it was opened earlier.
  return [...cases.values()].sort((a, b) => b.steps.at(-1).id - a.steps.at(-1).id)
}

function safetyTone(event) {
  if (event.includes('APPROVED')) return 'good'
  if (event.includes('BLOCKED') || event.includes('REJECTED')) return 'bad'
  return 'neutral'
}

function caseOutcome(steps) {
  const events = steps.map((step) => step.event)
  if (events.some((event) => event.startsWith('HUMAN APPROVED'))) return { label: 'Human approved', tone: 'good' }
  if (events.some((event) => event.startsWith('HUMAN REJECTED'))) return { label: 'Human rejected', tone: 'bad' }
  if (events.some((event) => event.startsWith('Refund'))) return { label: 'Auto-refunded', tone: 'good' }
  if (events.some((event) => event.startsWith('Ticket'))) return { label: 'Sent to a human', tone: 'wait' }
  return { label: 'In progress', tone: 'neutral' }
}

function StepDetail({ step }) {
  const { detail, stage, event } = step
  if (!detail) return null

  if (detail.checks) {
    return (
      <ul className="checks">
        {detail.checks.map((check) => (
          <li key={check.rule} className={check.passed ? 'check-pass' : 'check-fail'}>
            <span className="check-mark">{check.passed ? 'PASS' : 'FAIL'}</span>
            {check.detail}
          </li>
        ))}
      </ul>
    )
  }
  if (detail.flags) {
    return (
      <ul className="checks">
        {detail.flags.map((flag) => (
          <li key={flag} className="check-fail">
            <span className="check-mark">FLAG</span>
            {flag}
          </li>
        ))}
      </ul>
    )
  }
  if (stage === 'SENSE' && detail.text) return <p className="step-quote">{detail.text}</p>
  if (stage === 'SENSE' && detail.error) return <p className="step-note">{detail.error}</p>
  if (stage === 'SENSE' && detail.status) {
    return (
      <p className="step-note">
        {detail.status} · {detail.amount_inr} · {detail.payee_name}
        {detail.already_refunded ? ' · already refunded' : ''}
      </p>
    )
  }
  if (stage === 'AI' && detail.reason) return <p className="step-note">{detail.reason}</p>
  if (stage === 'AI' && detail.error) return <p className="step-note">{detail.error}</p>
  if (event === 'Reply sent to customer') return <p className="step-quote">{detail.reply}</p>
  return null
}

export default function DecisionLog() {
  const [entries, setEntries] = useState([])
  const lastId = useRef(0)

  const healthy = usePolling(async () => {
    const feed = await api.audit(lastId.current)
    if (feed.latest_id < lastId.current) {
      // The demo was reset, so what's on screen no longer exists.
      lastId.current = 0
      setEntries([])
      return
    }
    const fresh = feed.entries.filter((entry) => entry.id > lastId.current)
    if (fresh.length > 0) {
      lastId.current = fresh.at(-1).id
      setEntries((current) => [...current, ...fresh])
    }
  }, 600)

  const cases = useMemo(() => groupByCase(entries), [entries])

  return (
    <section className="panel" aria-labelledby="log-title">
      <div className="panel-header">
        <div>
          <h2 id="log-title">Live decision log</h2>
          <p className="stage-legend" aria-label="Every step is recorded as sense, then AI, then safety, then act">
            <span className="stage stage-sense">SENSE</span>
            <span aria-hidden="true">→</span>
            <span className="stage stage-ai">AI</span>
            <span aria-hidden="true">→</span>
            <span className="stage stage-safety-neutral">SAFETY</span>
            <span aria-hidden="true">→</span>
            <span className="stage stage-act">ACT</span>
          </p>
        </div>
        <span className={`live-pill ${healthy ? 'live-on' : 'live-off'}`}>{healthy ? 'Live' : 'Reconnecting'}</span>
      </div>

      <div className="panel-body" role="log" aria-live="polite">
        {cases.length === 0 && <p className="empty">Every step of every decision appears here as it happens.</p>}
        {cases.map((item) => {
          const outcome = caseOutcome(item.steps)
          return (
            <article key={item.caseId} className="case-card">
              <header className="case-header">
                <div>
                  <strong>{item.customerName}</strong>
                  <span className="case-id">{item.caseId}</span>
                </div>
                <span className={`outcome outcome-${outcome.tone}`}>{outcome.label}</span>
              </header>
              <ol className="steps">
                {item.steps.map((step) => (
                  <li key={step.id} className="step">
                    <span className={`stage stage-${step.stage === 'SAFETY' ? `safety-${safetyTone(step.event)}` : step.stage.toLowerCase()}`}>{step.stage}</span>
                    <div className="step-body">
                      <div className="step-line">
                        <span>{step.event}</span>
                        <time dateTime={step.created_at}>{TIME_FORMAT.format(new Date(step.created_at))}</time>
                      </div>
                      <StepDetail step={step} />
                    </div>
                  </li>
                ))}
              </ol>
            </article>
          )
        })}
      </div>
    </section>
  )
}
