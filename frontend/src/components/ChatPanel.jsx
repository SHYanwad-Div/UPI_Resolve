import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { usePolling } from '../usePolling'

const OUTCOMES = {
  auto_resolved: { label: 'Refund started', tone: 'good' },
  escalated: { label: 'With a specialist', tone: 'wait' },
  human_approved: { label: 'Approved by a specialist', tone: 'good' },
  human_rejected: { label: 'Not approved', tone: 'bad' },
}

const PAYMENT_STATUS = {
  failed_debited: 'Failed, money debited',
  failed_no_debit: 'Failed',
  pending: 'Pending',
  success: 'Successful',
}

const EMPTY_THREAD = { messages: [], caseId: null }

export default function ChatPanel() {
  const [customers, setCustomers] = useState([])
  const [customerId, setCustomerId] = useState('C01')
  const [threads, setThreads] = useState({})
  const [waitingOnHuman, setWaitingOnHuman] = useState([])
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const nextMessageId = useRef(1)
  const inputRef = useRef(null)
  const scrollRef = useRef(null)

  const thread = threads[customerId] ?? EMPTY_THREAD
  const customer = customers.find((c) => c.customer_id === customerId)

  function addMessage(toCustomerId, message) {
    const id = nextMessageId.current++
    setThreads((current) => {
      const existing = current[toCustomerId] ?? EMPTY_THREAD
      return { ...current, [toCustomerId]: { ...existing, messages: [...existing.messages, { id, ...message }] } }
    })
  }

  function setCaseId(toCustomerId, caseId) {
    setThreads((current) => ({ ...current, [toCustomerId]: { ...(current[toCustomerId] ?? EMPTY_THREAD), caseId } }))
  }

  usePolling(async () => {
    if (customers.length === 0) setCustomers(await api.customers())
  }, 2000)

  // A human decides in the other panel, so the chat checks for their answer.
  usePolling(async () => {
    for (const watched of waitingOnHuman) {
      let current
      try {
        current = await api.caseStatus(watched.caseId)
      } catch (error) {
        // A 404 means the demo was reset, so this case is gone. Anything else may be temporary.
        if (error.status === 404) setWaitingOnHuman((list) => list.filter((item) => item.caseId !== watched.caseId))
        continue
      }
      if (current.status !== 'escalated') {
        addMessage(watched.customerId, { from: 'resolve', text: current.reply, outcome: current.status })
        setWaitingOnHuman((list) => list.filter((item) => item.caseId !== watched.caseId))
      }
    }
  }, 1500)

  useEffect(() => {
    const box = scrollRef.current
    if (box) box.scrollTop = box.scrollHeight
  }, [thread.messages.length, sending])

  async function send(event) {
    event.preventDefault()
    const text = draft.trim()
    if (!text || sending) return

    const sender = customerId
    addMessage(sender, { from: 'customer', text })
    setDraft('')
    setSending(true)
    try {
      const result = await api.chat(sender, text, thread.caseId)
      addMessage(sender, { from: 'resolve', text: result.reply, outcome: result.status })
      // Only a case waiting for the customer's answer continues; anything else is finished.
      setCaseId(sender, result.status === 'awaiting_customer' ? result.case_id : null)
      if (result.status === 'escalated') {
        setWaitingOnHuman((list) => [...list, { caseId: result.case_id, customerId: sender }])
      }
    } catch (error) {
      addMessage(sender, { from: 'error', text: error.message })
    } finally {
      setSending(false)
      inputRef.current?.focus()
    }
  }

  function insertTransactionId(txnId) {
    setDraft((current) => (current ? `${current.trimEnd()} ${txnId} ` : `${txnId} `))
    inputRef.current?.focus()
  }

  return (
    <section className="panel" aria-labelledby="chat-title">
      <div className="panel-header">
        <div>
          <h2 id="chat-title">Customer chat</h2>
          <p className="panel-subtitle">What the customer sees</p>
        </div>
        <label className="customer-picker">
          <span>Chatting as</span>
          <select value={customerId} onChange={(event) => setCustomerId(event.target.value)} disabled={sending}>
            {customers.map((c) => (
              <option key={c.customer_id} value={c.customer_id}>
                {c.name} ({c.customer_id})
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="chat-messages" ref={scrollRef} role="log" aria-live="polite">
        <div className="bubble bubble-resolve">
          {customer ? `Hi ${customer.name.split(' ')[0]}, I'm Resolve. ` : "Hi, I'm Resolve. "}
          Tell me what went wrong with your payment, in English, हिंदी or ಕನ್ನಡ.
        </div>
        {thread.messages.map((message) => (
          <div key={message.id} className={`bubble bubble-${message.from}`}>
            {message.text}
            {OUTCOMES[message.outcome] && (
              <span className={`outcome outcome-${OUTCOMES[message.outcome].tone}`}>{OUTCOMES[message.outcome].label}</span>
            )}
          </div>
        ))}
        {sending && (
          <div className="bubble bubble-resolve typing" aria-label="Resolve is checking">
            <span />
            <span />
            <span />
          </div>
        )}
      </div>

      {customer && (
        <div className="payments">
          <p className="payments-title">Recent payments. Tap one to add its ID.</p>
          <ul className="payments-list">
            {customer.payments.map((payment) => (
              <li key={payment.txn_id}>
                <button type="button" className="payment" onClick={() => insertTransactionId(payment.txn_id)}>
                  <span className="payment-main">
                    <strong>{payment.payee_name}</strong>
                    <span>{payment.amount_inr}</span>
                  </span>
                  <span className="payment-meta">
                    <span>{payment.txn_id}</span>
                    <span>{PAYMENT_STATUS[payment.status]}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <form className="chat-form" onSubmit={send}>
        <input
          ref={inputRef}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Describe the problem..."
          aria-label="Your message"
          maxLength={2000}
          disabled={sending}
        />
        <button type="submit" className="button button-primary" disabled={sending || !draft.trim()}>
          Send
        </button>
      </form>
    </section>
  )
}
