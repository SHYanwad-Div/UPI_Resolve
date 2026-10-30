import { useEffect, useRef, useState } from 'react'

// Runs task, waits intervalMs, and repeats. Waiting after each finish, rather than using
// setInterval, means a slow response can never pile up overlapping requests.
// Returns false while the task is failing, so a panel can show that it is reconnecting.
export function usePolling(task, intervalMs) {
  const latestTask = useRef(task)
  const [healthy, setHealthy] = useState(true)

  useEffect(() => {
    latestTask.current = task
  })

  useEffect(() => {
    let stopped = false
    let timer

    async function tick() {
      try {
        await latestTask.current()
        if (!stopped) setHealthy(true)
      } catch {
        if (!stopped) setHealthy(false)
      }
      if (!stopped) timer = setTimeout(tick, intervalMs)
    }

    tick()
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [intervalMs])

  return healthy
}
