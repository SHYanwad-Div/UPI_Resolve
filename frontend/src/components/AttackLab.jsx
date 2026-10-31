import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { usePolling } from '../usePolling'

const AI_LABELS = {
  none: 'AI not reached',
  real: 'Real AI',
  scripted: 'Scripted AI',
}

function stageClass(step) {
  if (step.stage !== 'SAFETY') return `stage-${step.stage.toLowerCase()}`
  if (step.event.includes('APPROVED')) return 'stage-safety-good'
  if (step.event.includes('BLOCKED')) return 'stage-safety-bad'
  return 'stage-safety-neutral'
}

function groupResults(results) {
  const groups = new Map()
  for (const result of results) {
    if (!groups.has(result.group)) groups.set(result.group, [])
    groups.get(result.group).push(result)
  }
  return [...groups.entries()]
}

function AttackCard({ result }) {
  const verdict = !result.passed ? 'Not stopped' : result.is_control ? 'Refund paid correctly' : 'Stopped'
  return (
    <article className={`attack ${result.passed ? '' : 'attack-failed'}`}>
      <header className="attack-header">
        <strong>{result.title}</strong>
        <span className="attack-tags">
          <span className="outcome outcome-neutral">{AI_LABELS[result.ai]}</span>
          <span className={`outcome outcome-${result.passed ? 'good' : 'bad'}`}>{verdict}</span>
        </span>
      </header>
      <p className="attack-line">
        <span>{result.is_control ? 'Test:' : 'Attacker wants:'}</span> {result.goal}
      </p>
      {result.messages.map((message) => (
        <p key={message} className="step-quote">
          {message}
        </p>
      ))}
      <p className="attack-line">
        <span>{result.is_control ? 'Why:' : 'Stopped by:'}</span> {result.stopped_by}
      </p>
      <p className="attack-line">
        <span>Result:</span> {result.outcome}. Money moved: <strong>{result.money_moved_inr}</strong>
        {result.staff_warning ? '. Staff warned.' : '.'}
      </p>
      {result.ai_offline && <p className="approver-note">The real AI couldn't be reached, so this went to a person. No money moved.</p>}
      <details className="attack-details">
        <summary>See every step</summary>
        <ol className="steps">
          {result.steps.map((step, index) => (
            <li key={`${index}-${step.event}`} className="step">
              <span className={`stage ${stageClass(step)}`}>{step.stage}</span>
              <span>{step.event}</span>
            </li>
          ))}
        </ol>
        <p className="attack-line">
          <span>Customer saw:</span> {result.reply}
        </p>
        {result.staff_summary && (
          <p className="attack-line">
            <span>Staff saw:</span> {result.staff_summary}
          </p>
        )}
      </details>
    </article>
  )
}

export default function AttackLab({ onClose }) {
  const [state, setState] = useState(null)
  const [error, setError] = useState(null)
  const started = useRef(false)
  const closeButton = useRef(null)

  async function start() {
    setError(null)
    setState(null)
    try {
      setState(await api.simulateAttacks())
    } catch (failure) {
      // Already running is fine: the screen just follows the run in progress.
      if (failure.status !== 409) setError(failure.message)
    }
  }

  useEffect(() => {
    closeButton.current?.focus()
    if (started.current) return
    started.current = true
    start()
  }, [])

  useEffect(() => {
    function onKey(event) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  usePolling(async () => {
    setState(await api.attackStatus())
  }, 500)

  const results = state?.results ?? []
  const running = state ? state.running : true

  return (
    <div className="lab-overlay">
      <section className="lab" role="dialog" aria-modal="true" aria-labelledby="lab-title">
        <header className="lab-header">
          <div>
            <h2 id="lab-title">Attack simulation</h2>
            <p className="panel-subtitle">Every attack runs through the real system, on a throwaway copy of the data</p>
          </div>
          <div className="lab-actions">
            <button type="button" className="button button-secondary" disabled={running} onClick={start}>
              Run again
            </button>
            <button ref={closeButton} type="button" className="button button-primary" onClick={onClose}>
              Close
            </button>
          </div>
        </header>

        <dl className="stats lab-stats" aria-live="polite">
          <div className="stat">
            <dd>
              {state?.attacks_stopped ?? 0} of {state?.attacks_run ?? 0}
            </dd>
            <dt>Attacks stopped</dt>
          </div>
          <div className="stat">
            <dd>{state?.money_moved_by_attacks_inr ?? '₹0.00'}</dd>
            <dt>Money moved by attacks</dt>
          </div>
          <div className="stat">
            <dd>{running ? `Running ${results.length} of ${state?.total ?? '…'}` : 'Finished'}</dd>
            <dt>Status</dt>
          </div>
        </dl>

        {error && (
          <p className="ticket-error" role="alert">
            {error}
          </p>
        )}

        <div className="lab-body">
          {groupResults(results).map(([group, items]) => (
            <div key={group} className="lab-group">
              <h3>{group}</h3>
              {items.map((result) => (
                <AttackCard key={result.title} result={result} />
              ))}
            </div>
          ))}
          <p className="lab-note">
            <strong>Real AI</strong> is live Sarvam. <strong>Scripted AI</strong> is forced to misbehave, to prove the rules hold even if the AI is fully fooled. This shows these attacks fail. It doesn't prove every possible attack will. Your dashboard and scoreboard don't change.
          </p>
        </div>
      </section>
    </div>
  )
}
