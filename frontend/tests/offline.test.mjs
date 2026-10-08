import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import ts from 'typescript'

const compiled = ts.transpileModule(readFileSync('src/offlineQueue.ts', 'utf8'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText
const { drainQueue } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)
const coreUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`
const apiStubUrl = `data:text/javascript;base64,${Buffer.from('export const api = {}; export class ApiError extends Error {}; export const isNetworkError = () => false;').toString('base64')}`
const storageCode = ts.transpileModule(readFileSync('src/offline.ts', 'utf8'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText.replaceAll("'./api'", JSON.stringify(apiStubUrl)).replaceAll("'./offlineQueue'", JSON.stringify(coreUrl))
const { queueTransition, isPermanentQueueError } = await import(`data:text/javascript;base64,${Buffer.from(storageCode).toString('base64')}`)
const { ApiError: StubApiError } = await import(apiStubUrl)
test('photo 413/415/422 require queue conflict review, not endless automatic retries', () => {
  for (const status of [413,415,422]) {
    const error=new StubApiError('photo rejected');error.status=status
    assert.equal(isPermanentQueueError(error),true)
  }
  for (const status of [401,429,500,503]) {
    const error=new StubApiError('temporary/auth');error.status=status
    assert.equal(isPermanentQueueError(error),false)
  }
})
const action = (id, orderId = 10, userId = 1) => ({ id, userId, kind: 'transition', payload: { orderId, status: 'accepted' }, createdAt: '2026-10-07T00:00:00Z' })
function fixture(initial, send = async () => {}) {
  let records = [...initial]
  const sent = []
  const adapter = {
    list: async () => records,
    send: async record => { sent.push(record.id); await send(record) },
    remove: async id => { records = records.filter(record => record.id !== id) },
    save: async record => { records = records.map(item => item.id === record.id ? record : item) },
    isConflict: error => error.status === 409 || error.status === 422 || error.status === 403,
  }
  return { adapter, sent, records: () => records }
}
test('queue uses committed ID order even when timestamps are equal', async () => {
  const f = fixture([action(3), action(1), action(2)])
  assert.deepEqual(await drainQueue(1, f.adapter, () => true), { synced: 3, conflicts: 0, remaining: 0 })
  assert.deepEqual(f.sent, [1, 2, 3])
})
test('network failure keeps current action and all successors', async () => {
  const f = fixture([action(1), action(2)], async () => { throw new Error('Network') })
  assert.equal((await drainQueue(1, f.adapter, () => true)).remaining, 2)
  assert.deepEqual(f.sent, [1])
})
test('conflicting report and photos are retained, same-order successors blocked', async () => {
  const photo = new Blob(['photo'], { type: 'image/png' })
  const report = { ...action(1), kind: 'completion', payload: { orderId: 10, entries: [['work_performed', 'Заменён привод'], ['photos', photo]] } }
  const f = fixture([report, action(2), action(3, 20)], async record => {
    if (record.id === 1) throw Object.assign(new Error('Наряд уже изменён'), { status: 409 })
  })
  assert.deepEqual(await drainQueue(1, f.adapter, () => true), { synced: 1, conflicts: 1, remaining: 2 })
  assert.deepEqual(f.sent, [1, 3])
  assert.equal(f.records()[0].payload.entries[1][1], photo)
  assert.equal(f.records()[0].error, 'Наряд уже изменён')
})
test('stored conflicts are not automatically retried', async () => {
  const f = fixture([{ ...action(1), state: 'conflict' }, action(2), action(3, 20)])
  await drainQueue(1, f.adapter, () => true)
  assert.deepEqual(f.sent, [3])
})
test('foreign-user actions are never sent or removed', async () => {
  const f = fixture([action(1, 10, 2), action(2)])
  await drainQueue(1, f.adapter, () => true)
  assert.deepEqual(f.sent, [2])
  assert.equal(f.records()[0].userId, 2)
})
test('logout during a request stops subsequent sends', async () => {
  let active = true
  const f = fixture([action(1), action(2)], async () => { active = false })
  assert.equal((await drainQueue(1, f.adapter, () => active)).remaining, 1)
  assert.deepEqual(f.sent, [1])
})
test('401 and server errors retain queue without marking conflict', async () => {
  for (const status of [401, 500, 503]) {
    const f = fixture([action(1), action(2)], async () => { throw Object.assign(new Error('API'), { status }) })
    assert.deepEqual(await drainQueue(1, f.adapter, () => true), { synced: 0, conflicts: 0, remaining: 2 })
    assert.deepEqual(f.sent, [1])
  }
})
test('failure to commit removal is surfaced, not counted as success', async () => {
  const f = fixture([action(1)])
  f.adapter.remove = async () => { throw new Error('Storage abort') }
  await assert.rejects(drainQueue(1, f.adapter, () => true), /Storage abort/)
  assert.equal(f.records().length, 1)
})

test('lost server response keeps the same persisted key on retry', async () => {
  const keys = []
  let committed = false
  let events = 0
  const f = fixture([action(1)], async record => {
    keys.push(record.idempotencyKey)
    assert.equal(f.records()[0].idempotencyKey, record.idempotencyKey)
    if (!committed) {
      committed = true
      events++
      throw new Error('Reply lost after commit')
    }
    // Simulated server replay: no new event.
  })
  assert.equal((await drainQueue(1, f.adapter, () => true)).remaining, 1)
  assert.equal((await drainQueue(1, f.adapter, () => true)).remaining, 0)
  assert.equal(keys.length, 2)
  assert.match(keys[0], /^[a-f0-9-]{36}$/)
  assert.equal(keys[0], keys[1])
  assert.equal(events, 1)
})

test('failed persistence of a legacy key prevents any network send', async () => {
  const f = fixture([action(1)])
  f.adapter.save = async () => { throw new Error('Storage abort') }
  await assert.rejects(drainQueue(1, f.adapter, () => true), /Storage abort/)
  assert.deepEqual(f.sent, [])
})

test('failure to remove an acknowledged action safely retries its original key', async () => {
  const keys = []
  const f = fixture([action(1)], async record => keys.push(record.idempotencyKey))
  const remove = f.adapter.remove
  f.adapter.remove = async () => { throw new Error('Removal abort') }
  await assert.rejects(drainQueue(1, f.adapter, () => true), /Removal abort/)
  f.adapter.remove = remove
  assert.equal((await drainQueue(1, f.adapter, () => true)).synced, 1)
  assert.equal(keys[0], keys[1])
})

test('online UI paths persist before invoking the queue sender', () => {
  const source = readFileSync('src/App.vue', 'utf8')
  assert.ok(!source.includes('await api.transition('))
  assert.ok(!source.includes('await api.complete('))
  for (const method of ['queueTransition', 'queueCompletion']) {
    assert.ok(source.includes(`const actionId = await ${method}(`))
  }
})

// Explicit transaction events exercise the persistence wrapper, not a browser IDB implementation.
function storageEvents() {
  const request = { result: 1, error: null }
  const tx = { objectStore: () => ({ add: () => request }), error: null }
  let closed = false
  const db = { transaction: () => tx, close: () => { closed = true } }
  globalThis.indexedDB = { open: () => {
    const open = { result: db }
    queueMicrotask(() => open.onsuccess())
    return open
  } }
  return { request, tx, closed: () => closed }
}
test('saving resolves only after transaction commit, not request success', async () => {
  const previous = globalThis.indexedDB
  try {
    const f = storageEvents()
    let settled = false
    const saving = queueTransition(1, 10, 'accepted').then(result => { settled = true; return result })
    await new Promise(resolve => setImmediate(resolve))
    f.request.onsuccess?.()
    await Promise.resolve()
    assert.equal(settled, false)
    f.tx.oncomplete()
    assert.equal(await saving, 1)
    assert.equal(f.closed(), true)
  } finally { globalThis.indexedDB = previous }
})
test('transaction abort after request success rejects saving and closes DB', async () => {
  const previous = globalThis.indexedDB
  try {
    const f = storageEvents()
    const saving = queueTransition(1, 10, 'accepted')
    const rejection = assert.rejects(saving, /Quota exceeded/)
    await new Promise(resolve => setImmediate(resolve))
    f.request.onsuccess?.()
    f.tx.error = new Error('Quota exceeded')
    f.tx.onabort()
    await rejection
    assert.equal(f.closed(), true)
  } finally { globalThis.indexedDB = previous }
})
