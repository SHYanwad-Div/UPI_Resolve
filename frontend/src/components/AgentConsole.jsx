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

function OpenTicket({ ticket, now, onDecide }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function decide(action) {
    setBusy(true)
    setError(null)
    try {
      await onDecide(ticket.ticket_id, action)
    } catch (failure) {
      setError(failure.message)
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
      <p className="ticket-summary">{ticket.summary}</p>
      {ticket.refund_blocked_reason && <p className="ticket-blocked">Refund unavailable: {ticket.refund_blocked_reason}.</p>}
      {error && (
        <p className="ticket-error" role="alert">
          {error}
        </p>
      )}
      <div className="ticket-actions">
        <button type="button" className="button button-approve" disabled={busy || Boolean(ticket.refund_blocked_reason)} onClick={() => decide('approve')}>
          Approve refund
        </button>
        <button type="button" className="button button-reject" disabled={busy} onClick={() => decide('reject')}>
          Reject
        </button>
      </div>
    </article>
  )
}

export default function AgentConsole() {
  const [tickets, setTickets] = useState([])
  const now = useNow(30_000)

  async function refresh() {
    setTickets(await api.tickets())
  }

  usePolling(refresh, 1200)

  async function decide(ticketId, action) {
    await (action === 'approve' ? api.approve(ticketId) : api.reject(ticketId))
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
        <span className="queue-count">{open.length} waiting</span>
      </div>

      <div className="panel-body">
        {open.length === 0 && <p className="empty">Nothing needs a human right now.</p>}
        {open.map((ticket) => (
          <OpenTicket key={ticket.ticket_id} ticket={ticket} now={now} onDecide={decide} />
        ))}

        {decided.length > 0 && (
          <div className="decided">
            <h3>Decided</h3>
            <ul>
              {decided.map((ticket) => (
                <li key={ticket.ticket_id}>
                  <span>
                    {ticket.customer_name} · {ticket.ticket_id}
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
