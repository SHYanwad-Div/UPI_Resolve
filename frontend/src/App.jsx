import { useEffect, useState } from 'react'
import { setSignedOutHandler, setStaffToken } from './api'
import AgentConsole from './components/AgentConsole.jsx'
import AttackLab from './components/AttackLab.jsx'
import ChatPanel from './components/ChatPanel.jsx'
import DecisionLog from './components/DecisionLog.jsx'
import ScoreBar from './components/ScoreBar.jsx'

export default function App() {
  const [staff, setStaff] = useState(null)
  const [attacksOpen, setAttacksOpen] = useState(false)

  useEffect(() => {
    setSignedOutHandler(() => setStaff(null))
  }, [])

  function signIn(session) {
    setStaffToken(session.token)
    setStaff(session.name)
  }

  function signOut() {
    setStaffToken(null)
    setStaff(null)
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-name">Resolve</span>
          <span className="brand-tagline">The AI teammate that fixes failed UPI payments</span>
        </div>
        <div className="topbar-note">
          <span>Team Ghost Ops</span>
          <span className="mock-note">Demo data. No real money moves.</span>
        </div>
      </header>
      <ScoreBar staff={staff} onSimulateAttacks={() => setAttacksOpen(true)} />
      {attacksOpen && staff && <AttackLab onClose={() => setAttacksOpen(false)} />}
      <main className="panels">
        <ChatPanel />
        <DecisionLog staff={staff} />
        <AgentConsole staff={staff} onSignIn={signIn} onSignOut={signOut} />
      </main>
    </div>
  )
}
