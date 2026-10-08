import { api, ApiError, isNetworkError, type WorkOrderStatus } from './api'
import { drainQueue, type QueuedAction, type FlushResult } from './offlineQueue'
export type { QueuedAction } from './offlineQueue'

const DB_NAME = 'naryad-ai'
const STORE_NAME = 'action-queue'
const DB_VERSION = 2
const DRAFT_STORE = 'completion-drafts'

export interface CompletionDraft {
  key: string; userId: number; orderId: number; revision: string; updatedAt: string
  work_performed: string; fault_code_id: number; comment: string
  material_id: number | null; quantity: number
  usages: Array<{ material_id: number; quantity: number }>
  photo: File | null
  photoName?: string; photoModified?: number
}
export const completionDraftKey = (userId: number, orderId: number) => `${userId}:${orderId}`

function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION)
    let blocked = false
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE_NAME)) request.result.createObjectStore(STORE_NAME, { keyPath: 'id', autoIncrement: true })
      if (!request.result.objectStoreNames.contains(DRAFT_STORE)) request.result.createObjectStore(DRAFT_STORE, { keyPath: 'key' })
    }
    request.onsuccess = () => { if (blocked) { request.result.close(); return }; request.result.onversionchange = () => request.result.close(); resolve(request.result) }
    request.onerror = () => reject(request.error)
    request.onblocked = () => { blocked = true; reject(new Error('Закройте другие вкладки приложения для обновления хранилища')) }
  })
}

async function transaction<T>(mode: IDBTransactionMode, operation: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await database()
  return new Promise((resolve, reject) => {
    try {
      const tx = db.transaction(STORE_NAME, mode)
      const request = operation(tx.objectStore(STORE_NAME))
      tx.oncomplete = () => { db.close(); resolve(request.result) }
      tx.onabort = () => { db.close(); reject(tx.error ?? request.error ?? new Error('Не удалось сохранить действие на устройстве')) }
      tx.onerror = () => { /* The failed request aborts the transaction. */ }
    } catch (error) { db.close(); reject(error) }
  })
}

export function queueTransition(userId: number, orderId: number, status: WorkOrderStatus, comment?: string) {
  return transaction('readwrite', store => store.add({ userId, idempotencyKey: crypto.randomUUID(), kind: 'transition', payload: { orderId, status, comment }, createdAt: new Date().toISOString() } as QueuedAction))
}

export async function queueCompletion(userId: number, orderId: number, data: FormData, draftRevision?: string) {
  const entries = Array.from(data.entries())
  const db = await database()
  return new Promise<number>((resolve, reject) => {
    try {
      const tx = db.transaction([STORE_NAME, DRAFT_STORE], 'readwrite')
      const request = tx.objectStore(STORE_NAME).add({ userId, idempotencyKey: crypto.randomUUID(), kind: 'completion', payload: { orderId, entries }, createdAt: new Date().toISOString() } as QueuedAction)
      if (draftRevision) {
        const drafts = tx.objectStore(DRAFT_STORE)
        const previous = drafts.get(completionDraftKey(userId, orderId))
        previous.onsuccess = () => {
          if (previous.result?.revision === draftRevision) drafts.delete(completionDraftKey(userId, orderId))
        }
      }
      tx.oncomplete = () => { db.close(); resolve(Number(request.result)) }
      tx.onabort = () => { db.close(); reject(tx.error ?? request.error ?? new Error('Не удалось сохранить отчёт')) }
      tx.onerror = () => {}
    } catch (error) { db.close(); reject(error) }
  })
}

export async function loadCompletionDraft(userId: number, orderId: number): Promise<CompletionDraft | undefined> {
  const db = await database()
  return new Promise((resolve, reject) => {
    try {
      const tx = db.transaction(DRAFT_STORE, 'readonly')
      const request = tx.objectStore(DRAFT_STORE).get(completionDraftKey(userId, orderId))
      tx.oncomplete = () => { db.close(); resolve(request.result) }
      tx.onabort = () => { db.close(); reject(tx.error ?? request.error) }
      tx.onerror = () => {}
    } catch (error) { db.close(); reject(error) }
  })
}

export async function saveCompletionDraft(draft: CompletionDraft, expectedRevision?: string): Promise<void> {
  if (draft.key !== completionDraftKey(draft.userId, draft.orderId)) throw new Error('Некорректный владелец черновика')
  const db = await database()
  return new Promise((resolve, reject) => {
    let conflict: Error | undefined
    try {
      const tx = db.transaction(DRAFT_STORE, 'readwrite')
      const store = tx.objectStore(DRAFT_STORE)
      const previous = store.get(draft.key)
      previous.onsuccess = () => {
        if (previous.result?.revision !== expectedRevision) {
          conflict = new Error('Черновик изменён в другой вкладке. Текущие поля не сохранены; скопируйте их перед закрытием.')
          tx.abort()
        } else store.put(draft)
      }
      tx.oncomplete = () => { db.close(); resolve() }
      tx.onabort = () => { db.close(); reject(conflict ?? tx.error ?? previous.error ?? new Error('Не удалось сохранить черновик')) }
      tx.onerror = () => {}
    } catch (error) { db.close(); reject(error) }
  })
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

export async function queuedActions(userId: number): Promise<QueuedAction[]> {
  return (await actions()).filter(action => action.userId === userId).sort((a, b) => a.id! - b.id!)
}

export async function retryQueuedAction(userId: number, id: number) {
  const action = (await queuedActions(userId)).find(item => item.id === id)
  if (action) await transaction('readwrite', store => store.put({ ...action, state: 'pending', error: undefined }))
}

function restoreForm(entries: Array<[string, FormDataEntryValue]>): FormData {
  const data = new FormData()
  for (const [key, value] of entries) data.append(key, value)
  return data
}

const activeFlushes = new Map<number, Promise<FlushResult>>()
export const isPermanentQueueError = (error:unknown) => !isNetworkError(error) && error instanceof ApiError && [400,403,404,409,413,415,422].includes(error.status)
export function flushQueue(userId: number, isSessionActive: () => boolean): Promise<FlushResult> {
  const active = activeFlushes.get(userId)
  if (active) return active
  const run = () => drainQueue(userId, {
    list: actions,
    remove,
    save: action => transaction('readwrite', store => store.put(action)),
    isConflict: isPermanentQueueError,
    send: async action => {
      if (action.kind === 'transition') {
        const payload = action.payload
        await api.transition(payload.orderId, payload.status, payload.comment, action.idempotencyKey)
      } else {
        const payload = action.payload
        await api.complete(payload.orderId, restoreForm(payload.entries), action.idempotencyKey)
      }
    },
  }, isSessionActive)
  // Web Locks coordinate tabs on supported secure origins, including localhost.
  const promise = (async (): Promise<FlushResult> => {
    if (typeof navigator !== 'undefined' && navigator.locks) return await navigator.locks.request('naryad-action-queue', run)
    return run()
  })().finally(() => activeFlushes.delete(userId))
  activeFlushes.set(userId, promise)
  return promise
}
