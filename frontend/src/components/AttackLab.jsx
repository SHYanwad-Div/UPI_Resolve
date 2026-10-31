import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { usePolling } from '../usePolling'

const AI_LABELS = {
  none: 'AI not reached',
  real: 'Real AI',
  scripted: 'Scripted AI',
}

const LAYERS = [
  ['1. Message filter', 'Reads customer messages in English, Hindi and Kannada, removes invisible characters, and compares any stated amount with the record.'],
  ['2. Payment data scan', 'Checks payee names and notes, which outsiders write, for text that looks like instructions.'],
  ['3. Limited AI', "Never reads payee names or notes. It has no tool that moves money, and it can only pick reasons from a fixed list."],
  ['4. Rules', "Plain code decides from database facts, and a reason only reaches staff if the record agrees."],
  ['5. People', 'Named staff decide. Big or flagged refunds need two different people, and customers\' words are marked unverified.'],
]

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

function groupId(group) {
  return `attack-group-${group.replace(/[^a-z]/gi, '').toLowerCase()}`
}

function WhatTheAiSaw({ result }) {
  if (!result.ai_reached) {
    return <p className="attack-line">Nothing. The filter stopped this before the AI was used.</p>
  }
  return (
    <>
      <p className="attack-line">
        <span>Message it received:</span> {result.ai_got_message}
      </p>
      {result.ai_got_lookups.map((lookup, index) => (
        <p key={index} className="attack-line">
          <span>Payment data it received:</span> {lookup.error ?? `${lookup.txn_id}, ${lookup.status}, ${lookup.amount_inr}, already refunded: ${lookup.already_refunded ? 'yes' : 'no'}`}
        </p>
      ))}
      {result.hidden_text && (
        <p className={`attack-line ${result.ai_read_hidden ? 'attack-bad' : 'attack-good'}`}>
          {result.ai_read_hidden ? `The AI did read the ${result.hidden_field}.` : `The hidden ${result.hidden_field} never reached the AI. This was checked against everything it was sent.`}
        </p>
      )}
    </>
  )
}

function AttackCard({ result }) {
  const skipped = result.is_control && result.ai_offline // No refund was tested, so this is neither a pass nor a failure.
  const verdict = !result.passed ? 'Not stopped' : skipped ? 'Not tested: AI offline' : result.is_control ? 'Refund paid correctly' : 'Stopped'
  return (
    <article className={`attack ${result.passed ? '' : 'attack-failed'} ${result.hidden_text ? 'attack-bunq' : ''}`}>
      <header className="attack-header">
        <strong>{result.title}</strong>
        <span className="attack-tags">
          {result.hidden_text && <span className="outcome outcome-wait">Bunq-style</span>}
          <span className="outcome outcome-neutral">{AI_LABELS[result.ai]}</span>
          <span className={`outcome outcome-${skipped ? 'wait' : result.passed ? 'good' : 'bad'}`}>{verdict}</span>
        </span>
      </header>
      <p className="attack-line">
        <span>{result.is_control ? 'Test:' : 'Attacker wants:'}</span> {result.goal}
      </p>

      <h4>{result.is_control ? 'The message' : 'The injection'}</h4>
      <div className={result.is_control ? 'payload payload-honest' : 'payload'}>
        {result.messages.map((message, index) => (
          <p key={index}>
            <span>{result.messages.length > 1 ? `Customer message ${index + 1}:` : 'Customer typed:'}</span> {message}
          </p>
        ))}
        {result.hidden_text && (
          <p className="payload-hidden">
            <span>Hidden in the {result.hidden_field}. The customer never typed this:</span> {result.hidden_text}
          </p>
        )}
        {result.forced_calls.length > 0 && (
          <p>
            <span>We forced the AI to do this:</span> <code>{result.forced_calls.join(', then ')}</code>
          </p>
        )}
      </div>

      {!result.is_control && (
        <>
          <h4>How it was caught</h4>
          {result.caught.length > 0 ? (
            <ul className="caught">
              {result.caught.map((item, index) => (
                <li key={index}>
                  {item.how}
                  {item.matched && (
                    <>
                      {' '}
                      <mark>{item.matched}</mark>
                    </>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="attack-line">No detector flagged this one. It was stopped later, by the layer below.</p>
          )}
          <p className="attack-line">
            <span>Stopped by:</span> {result.stopped_by}
          </p>
        </>
      )}
      {result.is_control && <p className="attack-line">{result.stopped_by}</p>}

      <h4>What the AI saw</h4>
      <WhatTheAiSaw result={result} />
      {result.ai_offline && <p className="approver-note">The real AI couldn't be reached, so this went to a person. No money moved.</p>}

      {result.checks.length > 0 && (
        <>
          <h4>Rule checks</h4>
          <ul className="checks">
            {result.checks.map((check) => (
              <li key={check.rule} className={check.passed ? 'check-pass' : 'check-fail'}>
                <span className="check-mark">{check.passed ? 'PASS' : 'FAIL'}</span>
                {check.detail}
              </li>
            ))}
          </ul>
        </>
      )}

      <h4>Result</h4>
      <p className="attack-line">
        {result.outcome}. Money moved: <strong>{result.money_moved_inr}</strong>.{result.staff_warning ? ' Staff were warned.' : ''}
        {result.needs_two_people ? ' Two different people must approve.' : ''}
      </p>

      <details className="attack-details">
        <summary>See every step, and what people saw</summary>
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
        {result.customer_words && (
          <p className="attack-line">
            <span>Shown to staff apart, marked unverified:</span> {result.customer_words}
          </p>
        )}
        {result.customer_words_hidden && <p className="attack-line attack-good">The customer's words were hidden from staff, with a warning.</p>}
      </details>
    </article>
  )
}

export default function AttackLab({ onClose }) {
  const [state, setState] = useState(null)
  const [error, setError] = useState(null)
  const started = useRef(false)
  const closeButton = useRef(null)
  const bodyRef = useRef(null)

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
  const groups = groupResults(results)

  function jumpTo(group) {
    bodyRef.current?.querySelector(`#${groupId(group)}`)?.scrollIntoView({ block: 'start' })
  }

  return (
    <div className="lab-overlay">
      <section className="lab" role="dialog" aria-modal="true" aria-labelledby="lab-title">
        <header className="lab-header">
          <div>
            <h2 id="lab-title">Prompt injection dashboard</h2>
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

        {groups.length > 0 && (
          <nav className="lab-jump" aria-label="Jump to a group of attacks">
            {groups.map(([group, items]) => (
              <button key={group} type="button" onClick={() => jumpTo(group)}>
                {group} ({items.length})
              </button>
            ))}
          </nav>
        )}

        {error && (
          <p className="ticket-error" role="alert">
            {error}
          </p>
        )}

        <div className="lab-body" ref={bodyRef}>
          <details className="layers">
            <summary>How Resolve detects and stops prompt injection (5 layers)</summary>
            <ol>
              {LAYERS.map(([name, text]) => (
                <li key={name}>
                  <strong>{name}:</strong> {text}
                </li>
              ))}
            </ol>
          </details>

          {groups.map(([group, items]) => (
            <div key={group} id={groupId(group)} className="lab-group">
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
