import { api, ApiError, isNetworkError, type WorkOrderStatus } from './api'

const DB_NAME = 'naryad-ai'
const STORE_NAME = 'action-queue'
const DB_VERSION = 1

type TransitionPayload = { orderId: number; status: WorkOrderStatus; comment?: string }
type CompletionPayload = { orderId: number; entries: Array<[string, FormDataEntryValue]> }
type QueuedAction = {
  id?: number
  userId: number
  kind: 'transition' | 'completion'
  payload: TransitionPayload | CompletionPayload
  createdAt: string
}

function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION)
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE_NAME)) request.result.createObjectStore(STORE_NAME, { keyPath: 'id', autoIncrement: true })
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

async function transaction<T>(mode: IDBTransactionMode, operation: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await database()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, mode)
    const request = operation(tx.objectStore(STORE_NAME))
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
    tx.oncomplete = () => db.close()
  })
}

export function queueTransition(userId: number, orderId: number, status: WorkOrderStatus, comment?: string) {
  return transaction('readwrite', store => store.add({ userId, kind: 'transition', payload: { orderId, status, comment }, createdAt: new Date().toISOString() } as QueuedAction))
}

export function queueCompletion(userId: number, orderId: number, data: FormData) {
  const entries = Array.from(data.entries())
  return transaction('readwrite', store => store.add({ userId, kind: 'completion', payload: { orderId, entries }, createdAt: new Date().toISOString() } as QueuedAction))
}

async function actions(): Promise<QueuedAction[]> {
  return transaction('readonly', store => store.getAll())
}

async function remove(id: number) {
  await transaction('readwrite', store => store.delete(id))
}

export async function queuedCount(userId: number): Promise<number> {
  return (await actions()).filter(action => action.userId === userId).length
}

function restoreForm(entries: Array<[string, FormDataEntryValue]>): FormData {
  const data = new FormData()
  for (const [key, value] of entries) data.append(key, value)
  return data
}

export async function flushQueue(userId: number): Promise<{ synced: number; discarded: number; remaining: number }> {
  let synced = 0
  let discarded = 0
  const pending = (await actions()).filter(action => action.userId === userId).sort((a, b) => a.createdAt.localeCompare(b.createdAt))
  for (const action of pending) {
    try {
      if (action.kind === 'transition') {
        const payload = action.payload as TransitionPayload
        await api.transition(payload.orderId, payload.status, payload.comment)
      } else {
        const payload = action.payload as CompletionPayload
        await api.complete(payload.orderId, restoreForm(payload.entries))
      }
      await remove(action.id!)
      synced += 1
    } catch (error) {
      if (isNetworkError(error)) break
      if (error instanceof ApiError && [403, 404, 409, 422].includes(error.status)) {
        await remove(action.id!)
        discarded += 1
        continue
      }
      break
    }
  }
  return { synced, discarded, remaining: await queuedCount(userId) }
}
