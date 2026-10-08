import type { WorkOrderStatus } from './api'

export type QueuedAction = {
  id?: number
  userId: number
  idempotencyKey?: string
  createdAt: string
  state?: 'pending' | 'conflict'
  error?: string
} & (
  { kind: 'transition'; payload: { orderId: number; status: WorkOrderStatus; comment?: string } } |
  { kind: 'completion'; payload: { orderId: number; entries: Array<[string, FormDataEntryValue]> } }
)

export type FlushResult = { synced: number; conflicts: number; remaining: number }
export interface QueueAdapter {
  list(): Promise<QueuedAction[]>
  send(action: QueuedAction): Promise<unknown>
  remove(id: number): Promise<unknown>
  save(action: QueuedAction): Promise<unknown>
  isConflict(error: unknown): boolean
}

// Process committed records in ID order. A conflict blocks only its own order.
export async function drainQueue(userId: number, adapter: QueueAdapter, isSessionActive: () => boolean): Promise<FlushResult> {
  let synced = 0
  const blockedOrders = new Set<number>()
  const pending = (await adapter.list()).filter(action => action.userId === userId).sort((a, b) => a.id! - b.id!)
  for (const action of pending) {
    if (!isSessionActive()) break
    if (action.state === 'conflict') blockedOrders.add(action.payload.orderId)
    if (blockedOrders.has(action.payload.orderId)) continue
    // Upgrade old committed records before the first retry; never send an unpersisted key.
    if (!action.idempotencyKey) {
      action.idempotencyKey = crypto.randomUUID()
      await adapter.save(action)
    }
    try {
      await adapter.send(action)
    } catch (error) {
      if (!adapter.isConflict(error)) break // network, auth and server failures remain queued
      await adapter.save({ ...action, state: 'conflict', error: error instanceof Error ? error.message : 'Действие отклонено сервером' })
      blockedOrders.add(action.payload.orderId)
      continue
    }
    // Storage failure must not be misclassified as a rejected API action.
    await adapter.remove(action.id!)
    synced++
  }
  const remaining = (await adapter.list()).filter(action => action.userId === userId)
  return { synced, conflicts: remaining.filter(action => action.state === 'conflict').length, remaining: remaining.length }
}
