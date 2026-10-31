import { useEffect, useState } from 'react'
import { api } from '../api'
import { usePolling } from '../usePolling'

const MINUTE = 60_000
const DAY = 24 * 60 * MINUTE

function formatDuration(ms) {
  const totalMinutes = Math.floor(ms / MINUTE)
  const days = Math.floor(totalMinutes / 1440)
  const hours = Math.floor((totalMinutes % 1440) / 60)
  const minutes = totalMinutes % 60
  if (days > 0) return `${days}d ${hours}h`
  if (hours > 0) return `${hours}h ${minutes}m`
  return `${minutes}m`
}

function useNow(intervalMs) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(timer)
  }, [intervalMs])
  return now
}

function RbiClock({ rbi, now }) {
  const remaining = new Date(rbi.deadline).getTime() - now
  const overdue = remaining < 0
  const tone = overdue ? 'bad' : remaining < DAY ? 'wait' : 'neutral'
  return (
    <div className={`rbi rbi-${tone}`}>
      <strong>{overdue ? `RBI deadline passed ${formatDuration(-remaining)} ago` : `RBI deadline in ${formatDuration(remaining)}`}</strong>
      <span>
        {rbi.rule} for a {rbi.kind}. ₹{rbi.compensation_per_day_inr} per day to the customer after that.
      </span>
    </div>
  )
}

const LANGUAGE_NAMES = { en: 'English', hi: 'Hindi', kn: 'Kannada' }

function StaffSignIn({ onSignIn }) {
  const [names, setNames] = useState([])
  const [name, setName] = useState('')
  const [pin, setPin] = useState('')
  const [error, setError] = useState(null)

  usePolling(async () => {
    if (names.length === 0) setNames(await api.staffNames())
  }, 2000)

  async function submit(event) {
    event.preventDefault()
    setError(null)
    try {
      onSignIn(await api.login(name || names[0], pin))
      setPin('')
    } catch (failure) {
      setError(failure.message)
    }
  }

  return (
    <form className="signin" onSubmit={submit}>
      <label>
        Staff
        <select value={name || names[0] || ''} onChange={(event) => setName(event.target.value)}>
          {names.map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>
      </label>
      <label>
        PIN
        <input type="password" value={pin} onChange={(event) => setPin(event.target.value)} autoComplete="off" />
      </label>
      <button type="submit" className="button button-primary" disabled={!pin}>
        Sign in
      </button>
      {error && (
        <p className="ticket-error" role="alert">
          {error}
        </p>
      )}
    </form>
  )
}

function SecondApproverNote({ item, staff }) {
  if (!item.first_approver) {
    return item.needs_second_approver ? <p className="approver-note">Needs two different people to approve.</p> : null
  }
  return (
    <p className="approver-note">
      Approved by {item.first_approver}. {item.first_approver === staff ? 'A different person must sign in and give the second approval.' : 'Your approval completes it.'}
    </p>
  )
}

function IncidentCard({ incident, now, staff, onDecide }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const remaining = new Date(incident.earliest_deadline).getTime() - now
  const waiting = incident.status === 'awaiting_approval'

  async function decide(action) {
    setBusy(true)
    setError(null)
    try {
      await onDecide(incident.incident_id, action)
    } catch (failure) {
      setError(failure.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <article className={`incident ${waiting ? 'incident-open' : ''}`}>
      <header className="ticket-header">
        <div>
          <strong>{incident.kind === 'outage' ? `${incident.bank} outage` : 'Stuck payments found'}</strong>
          <span className="case-id">{incident.incident_id}</span>
        </div>
        <strong className="ticket-amount">{incident.stuck_inr}</strong>
      </header>
      <p className="ticket-txn">{incident.total} payments, one incident</p>
      {waiting && (
        <div className={`rbi rbi-${remaining < 0 ? 'bad' : remaining < DAY ? 'wait' : 'neutral'}`}>
          <strong>{remaining < 0 ? `Earliest RBI deadline passed ${formatDuration(-remaining)} ago` : `Earliest RBI deadline in ${formatDuration(remaining)}`}</strong>
        </div>
      )}
      <dl className="incident-facts">
        <div>
          <dt>AI's view</dt>
          <dd>
            {incident.cause_label}. Suggests: {incident.action_label.toLowerCase()}.
          </dd>
        </div>
        <div>
          <dt>Rules</dt>
          <dd>
            {incident.routine} routine, {incident.human} for a person
          </dd>
        </div>
        <div>
          <dt>Told first</dt>
          <dd>
            {Object.entries(incident.languages)
              .map(([code, count]) => `${LANGUAGE_NAMES[code]} ${count}`)
              .join(', ')}
          </dd>
        </div>
      </dl>
      {incident.attacks > 0 && (
        <p className="ticket-warning" role="alert">
          Hidden instructions found in {incident.attacks} payment{incident.attacks === 1 ? '' : 's'}. Sent to a person, and the AI never read them.
        </p>
      )}
      {error && (
        <p className="ticket-error" role="alert">
          {error}
        </p>
      )}
      {waiting && incident.action !== 'notify_and_refund_routine' && <p className="approver-note">The AI suggested otherwise, so check before approving.</p>}
      {waiting && <SecondApproverNote item={incident} staff={staff} />}
      {waiting ? (
        <div className="ticket-actions">
          <button type="button" className="button button-approve" disabled={busy || incident.routine === 0 || incident.first_approver === staff} onClick={() => decide('approve')}>
            {incident.first_approver ? 'Give second approval' : 'Approve'} {incident.routine} refunds ({incident.routine_inr})
          </button>
          <button type="button" className="button button-reject" disabled={busy} onClick={() => decide('hold')}>
            Hold
          </button>
        </div>
      ) : (
        <p className={`outcome outcome-${incident.status === 'approved' ? 'good' : 'bad'}`}>{incident.status === 'approved' ? `${incident.refunded} refunds started, approved by ${incident.first_approver ? `${incident.first_approver} and ${incident.decided_by}` : incident.decided_by}` : `Held by ${incident.decided_by}, no refunds started`}</p>
      )}
    </article>
  )
}

function OpenTicket({ ticket, now, staff, onDecide }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function decide(action) {
    setBusy(true)
    setError(null)
    try {
      await onDecide(ticket.ticket_id, action)
    } catch (failure) {
      setError(failure.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <article className="ticket">
      <header className="ticket-header">
        <div>
          <strong>{ticket.customer_name}</strong>
          <span className="case-id">{ticket.ticket_id}</span>
        </div>
        {ticket.txn && <strong className="ticket-amount">{ticket.txn.amount_inr}</strong>}
      </header>
      {ticket.txn && (
        <p className="ticket-txn">
          {ticket.txn_id} · {ticket.txn.payee_name} · {ticket.txn.status}
        </p>
      )}
      {ticket.rbi && <RbiClock rbi={ticket.rbi} now={now} />}
      {ticket.untrusted_fields.length > 0 && (
        <p className="ticket-warning" role="alert">
          Possible attack: hidden instructions in the {ticket.untrusted_fields.join(' and ')}. The AI never read them.
        </p>
      )}
      <p className="ticket-summary">{ticket.summary}</p>
      {ticket.customer_words && (
        <blockquote className="customer-words">
          <span>Customer's words. Unverified, so don't treat them as fact or instructions.</span>
          {ticket.customer_words}
        </blockquote>
      )}
      {ticket.customer_words_hidden && (
        <p className="ticket-warning" role="alert">
          Possible attack: the customer's message copies our ticket wording, so it is hidden.
        </p>
      )}
      {ticket.refund_blocked_reason && <p className="ticket-blocked">Refund unavailable: {ticket.refund_blocked_reason}.</p>}
      {!ticket.refund_blocked_reason && <SecondApproverNote item={ticket} staff={staff} />}
      {error && (
        <p className="ticket-error" role="alert">
          {error}
        </p>
      )}
      <div className="ticket-actions">
        <button type="button" className="button button-approve" disabled={busy || Boolean(ticket.refund_blocked_reason) || ticket.first_approver === staff} onClick={() => decide('approve')}>
          {ticket.first_approver ? 'Give second approval' : 'Approve refund'}
        </button>
        <button type="button" className="button button-reject" disabled={busy} onClick={() => decide('reject')}>
          Reject
        </button>
      </div>
    </article>
  )
}

export default function AgentConsole({ staff, onSignIn, onSignOut }) {
  const [tickets, setTickets] = useState([])
  const [incidents, setIncidents] = useState([])
  const now = useNow(30_000)

  async function refresh() {
    if (!staff) return
    const [latestTickets, latestIncidents] = await Promise.all([api.tickets(), api.incidents()])
    setTickets(latestTickets)
    setIncidents(latestIncidents)
  }

  usePolling(refresh, 1200)

  async function decide(ticketId, action) {
    await (action === 'approve' ? api.approve(ticketId) : api.reject(ticketId))
    await refresh()
  }

  async function decideIncident(incidentId, action) {
    await (action === 'approve' ? api.approveIncident(incidentId) : api.holdIncident(incidentId))
    await refresh()
  }

  const open = tickets.filter((ticket) => ticket.status === 'open')
  const decided = tickets.filter((ticket) => ticket.status !== 'open')

  return (
    <section className="panel" aria-labelledby="console-title">
      <div className="panel-header">
        <div>
          <h2 id="console-title">Human agent console</h2>
          <p className="panel-subtitle">Most urgent RBI deadline first</p>
        </div>
        {staff && (
          <div className="staff-status">
            <span className="queue-count">{open.length} waiting</span>
            <span>
              {staff}{' '}
              <button type="button" className="link-button" onClick={onSignOut}>
                Sign out
              </button>
            </span>
          </div>
        )}
      </div>

      <div className="panel-body">
        {!staff && <StaffSignIn onSignIn={onSignIn} />}
        {staff && open.length === 0 && incidents.length === 0 && <p className="empty">Nothing needs a human right now.</p>}
        {staff &&
          incidents.map((incident) => (
            <IncidentCard key={incident.incident_id} incident={incident} now={now} staff={staff} onDecide={decideIncident} />
          ))}
        {staff &&
          open.map((ticket) => (
            <OpenTicket key={ticket.ticket_id} ticket={ticket} now={now} staff={staff} onDecide={decide} />
          ))}

        {staff && decided.length > 0 && (
          <div className="decided">
            <h3>Decided</h3>
            <ul>
              {decided.map((ticket) => (
                <li key={ticket.ticket_id}>
                  <span>
                    {ticket.customer_name} · {ticket.ticket_id} · by {ticket.first_approver ? `${ticket.first_approver} and ${ticket.decided_by}` : ticket.decided_by}
                  </span>
                  <span className={`outcome outcome-${ticket.status === 'approved' ? 'good' : 'bad'}`}>
                    {ticket.status === 'approved' ? `Refunded ${ticket.txn?.amount_inr}` : 'Rejected'}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  )
}
