import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import ts from 'typescript'

const code = ts.transpileModule(readFileSync('src/utils/endpoints.ts', 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText
const { apiBase, websocketBase } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)

test('dev endpoint defaults remain unchanged', () => {
  assert.equal(apiBase(undefined), 'http://localhost:8000')
  assert.equal(websocketBase(undefined, 'http://localhost:5173'), 'ws://localhost:8000')
})
test('HTTPS build uses same-origin API and WSS including nonstandard port', () => {
  assert.equal(apiBase(''), '')
  assert.equal(websocketBase('', 'https://192.168.1.114:8443'), 'wss://192.168.1.114:8443')
  assert.equal(websocketBase('', 'http://localhost:15173'), 'ws://localhost:15173')
})
test('explicit endpoint overrides preserve ports and remove trailing slash', () => {
  assert.equal(apiBase('https://api.example.test/'), 'https://api.example.test')
  assert.equal(websocketBase('wss://api.example.test:8443/', 'https://page.example.test'), 'wss://api.example.test:8443')
})
