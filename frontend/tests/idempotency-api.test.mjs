import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import ts from 'typescript'

const endpointsCode = ts.transpileModule(readFileSync('src/utils/endpoints.ts', 'utf8'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText
const endpointsModule = `data:text/javascript;base64,${Buffer.from(endpointsCode).toString('base64')}`
const compiled = ts.transpileModule(readFileSync('src/api.ts', 'utf8'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText.replaceAll('import.meta.env', '({})').replace("'./utils/endpoints'", JSON.stringify(endpointsModule))
const { api } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)

test('JSON and multipart API requests transmit the same idempotency header', async () => {
  const oldFetch = globalThis.fetch
  const oldStorage = globalThis.localStorage
  try {
    const sent = []
    globalThis.localStorage = { getItem: () => 'token' }
    globalThis.fetch = async (url, options) => {
      sent.push({ url, ...options })
      return { ok: true, json: async () => ({ id: 10 }) }
    }
    const key = crypto.randomUUID()
    await api.transition(10, 'accepted', undefined, key)
    const form = new FormData()
    form.append('work_performed', 'Replaced seal')
    await api.complete(10, form, key)
    assert.equal(sent[0].headers['Idempotency-Key'], key)
    assert.equal(sent[1].headers['Idempotency-Key'], key)
    assert.equal(sent[1].headers.Authorization, 'Bearer token')
    assert.equal(sent[1].headers['Content-Type'], undefined)
    assert.equal(sent[1].body, form)
  } finally {
    globalThis.fetch = oldFetch
    globalThis.localStorage = oldStorage
  }
})
