export type Recovery<T> = { state: 'confirmed'; user: T } | { state: 'none' | 'changed' | 'expired' | 'unavailable' }

// A network/server failure does not prove that a saved session is invalid.
export async function recoverSession<T>(fetchUser: () => Promise<T>, readToken: () => string | null): Promise<Recovery<T>> {
  const token = readToken()
  if (!token) return { state: 'none' }
  try {
    const user = await fetchUser()
    return readToken() === token ? { state: 'confirmed', user } : { state: 'changed' }
  } catch (error) {
    if (readToken() !== token) return { state: 'changed' }
    const status = error && typeof error === 'object' && 'status' in error ? error.status : null
    return { state: status === 401 || status === 403 ? 'expired' : 'unavailable' }
  }
}
