// Undefined keeps dev defaults; explicitly empty selects the page origin.
export function apiBase(configured: string | undefined): string {
  return (configured ?? 'http://localhost:8000').replace(/\/+$/, '')
}

export function websocketBase(configured: string | undefined, pageOrigin: string): string {
  if (configured === undefined) return 'ws://localhost:8000'
  if (configured.trim()) return configured.replace(/\/+$/, '')
  const url = new URL(pageOrigin)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.origin
}
