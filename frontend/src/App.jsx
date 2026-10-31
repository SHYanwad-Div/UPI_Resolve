import AgentConsole from './components/AgentConsole.jsx'
import ChatPanel from './components/ChatPanel.jsx'
import DecisionLog from './components/DecisionLog.jsx'
import ScoreBar from './components/ScoreBar.jsx'

export default function App() {
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
      <ScoreBar />
      <main className="panels">
        <ChatPanel />
        <DecisionLog />
        <AgentConsole />
      </main>
    </div>
  )
}
