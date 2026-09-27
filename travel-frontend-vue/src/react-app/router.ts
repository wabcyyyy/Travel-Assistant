import { useCallback, useEffect, useState } from 'react'

export interface LocationState {
  path: string
  query: URLSearchParams
}

function readLocation(): LocationState {
  // Retired creation pages share the homepage form; preserve bookmarked input.
  if (['/plan', '/generate'].includes(window.location.pathname)) {
    window.history.replaceState({}, '', `/${window.location.search}`)
  }
  return { path: window.location.pathname, query: new URLSearchParams(window.location.search) }
}

export function navigate(to: string) {
  if (to === window.location.pathname + window.location.search) return
  window.history.pushState({}, '', to)
  window.dispatchEvent(new PopStateEvent('popstate'))
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

export function loginRedirect(path = `${window.location.pathname}${window.location.search}`) {
  return `/login?redirect=${encodeURIComponent(path || '/')}`
}

export function useLocation() {
  const [location, setLocation] = useState<LocationState>(() => readLocation())
  useEffect(() => {
    const onPopState = () => setLocation(readLocation())
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])
  const go = useCallback((to: string) => navigate(to), [])
  return { ...location, navigate: go }
}

export function routeId(path: string, prefix: string): string | null {
  if (!path.startsWith(prefix)) return null
  const rest = path.slice(prefix.length).split('/').filter(Boolean)
  return rest[0] || null
}
