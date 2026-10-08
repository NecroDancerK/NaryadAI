import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import ts from 'typescript'

const stub = `data:text/javascript;base64,${Buffer.from('export const api={}; export class ApiError extends Error {}; export const isNetworkError=()=>false; export const drainQueue=()=>{};').toString('base64')}`
const code = ts.transpileModule(readFileSync('src/offline.ts','utf8'), {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText.replaceAll("'./api'",JSON.stringify(stub)).replaceAll("'./offlineQueue'",JSON.stringify(stub))
const {completionDraftKey,saveCompletionDraft,loadCompletionDraft,queueCompletion} = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)

// Deterministic transaction adapter. Browser acceptance covers real IndexedDB.
function storage(initial) {
  const rows = new Map(initial.map(draft => [draft.key,structuredClone(draft)]))
  const queue = []
  let abortNext = false
  globalThis.indexedDB = {open:() => {
    const db = {close(){},transaction(names,mode) {
      const snapshot = new Map(rows)
      const additions = []
      let pending = 0, done = false, error
      const tx = {error:null,abort() { done=true; queueMicrotask(() => tx.onabort?.()) },objectStore(name) {
        return {
          get(key) { return request(() => snapshot.get(key)) },
          put(value) { return request(() => {snapshot.set(value.key,structuredClone(value));return value.key}) },
          delete(key) { return request(() => snapshot.delete(key)) },
          add(value) { return request(() => { additions.push(structuredClone(value));return queue.length+additions.length }) },
        }
      }}
      function request(operation) {
        const req = {}; pending++
        queueMicrotask(() => {
          if (done) return
          req.result = operation(); req.onsuccess?.(); pending--
          if (!pending && !done) queueMicrotask(() => {
            if (done || pending) return
            done=true
            if (abortNext) { abortNext=false;tx.error=new Error('Quota exceeded');tx.onabort?.();return }
            if (mode==='readwrite') { rows.clear();for(const [key,value] of snapshot)rows.set(key,value);queue.push(...additions) }
            tx.oncomplete?.()
          })
        })
        return req
      }
      return tx
    }}
    const req = {result:db};queueMicrotask(() => req.onsuccess());return req
  }}
  return {rows,queue,abort:()=>{abortNext=true}}
}
const draft = (revision='one',userId=1,orderId=10) => ({key:completionDraftKey(userId,orderId),userId,orderId,revision,work_performed:'Заменён уплотнитель',fault_code_id:1,comment:'Проверено',material_id:null,quantity:1,usages:[{material_id:1,quantity:2}],photo:null,updatedAt:'2026-10-08'})
test('drafts are isolated by user and order and survive committed writes', async () => {
  const old = globalThis.indexedDB
  try {
    storage([])
    await saveCompletionDraft(draft())
    assert.deepEqual(await loadCompletionDraft(1,10),draft())
    assert.equal(await loadCompletionDraft(2,10),undefined)
    assert.equal(await loadCompletionDraft(1,11),undefined)
  } finally {globalThis.indexedDB=old}
})
test('stale tab cannot overwrite another draft revision', async () => {
  const old = globalThis.indexedDB
  try {
    const s = storage([draft('newer')])
    await assert.rejects(saveCompletionDraft(draft('stale'),'one'),/другой вкладке/)
    assert.equal(s.rows.get('1:10').revision,'newer')
  } finally {globalThis.indexedDB=old}
})
test('completion queue handoff removes only the submitted draft in the same transaction', async () => {
  const old = globalThis.indexedDB
  try {
    const s = storage([draft(),draft('other',2)])
    const form = new FormData();form.append('work_performed','Заменён уплотнитель');form.append('photo',new File(['photo'],'repair.jpg',{type:'image/jpeg'}))
    await queueCompletion(1,10,form,'one')
    assert.equal(s.rows.has('1:10'),false)
    assert.equal(s.rows.has('2:10'),true)
    assert.equal(s.queue.length,1)
    assert.equal(s.queue[0].payload.entries[1][1].size,5)
  } finally {globalThis.indexedDB=old}
})
test('queue transaction failure retains draft and commits no report', async () => {
  const old = globalThis.indexedDB
  try {
    const s = storage([draft()]);s.abort()
    await assert.rejects(queueCompletion(1,10,new FormData(),'one'),/Quota/)
    assert.equal(s.queue.length,0)
    assert.equal(s.rows.get('1:10').revision,'one')
  } finally {globalThis.indexedDB=old}
})
test('handoff does not delete a newer revision from another tab', async () => {
  const old = globalThis.indexedDB
  try {
    const s = storage([draft('newer')])
    await queueCompletion(1,10,new FormData(),'one')
    assert.equal(s.rows.get('1:10').revision,'newer')
    assert.equal(s.queue.length,1)
  } finally {globalThis.indexedDB=old}
})
test('completion dialog does not promise automatic AI acceptance', () => {
  const component = readFileSync('src/components/CompletionDialog.vue','utf8')
  assert.doesNotMatch(component,/Далее — автоматическая проверка/)
  assert.match(component,/Решение о приёмке принимает человек/)
})
