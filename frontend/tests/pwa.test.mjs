import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync, existsSync } from 'node:fs'
import ts from 'typescript'

const code = ts.transpileModule(readFileSync('src/utils/sessionRecovery.ts', 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText
const { recoverSession } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)
test('network/server failure retains session without authenticating offline', async () => {
  for (const error of [new TypeError('network'), {status:500}, {status:503}, {status:429}]) {
    const result = await recoverSession(async () => { throw error }, () => 'saved-token')
    assert.deepEqual(result, {state:'unavailable'})
  }
})
test('only explicit denial expires a saved session', async () => {
  for (const status of [401,403]) assert.deepEqual(await recoverSession(async () => { throw {status} }, () => 'saved-token'), {state:'expired'})
})
test('missing token does not send a request', async () => {
  assert.deepEqual(await recoverSession(async () => { throw new Error('Must not be called') }, () => null), {state:'none'})
})
test('confirmed server identity restores the session', async () => {
  const user = {id:2,role:'worker'}
  assert.deepEqual(await recoverSession(async () => user, () => 'saved-token'), {state:'confirmed',user})
})
test('late identity/error cannot restore a logged-out or changed session', async () => {
  let token = 'old'
  assert.deepEqual(await recoverSession(async () => { token='new'; return {id:1} }, () => token), {state:'changed'})
  token='old'
  assert.deepEqual(await recoverSession(async () => { token=null; throw {status:503} }, () => token), {state:'changed'})
})
test('PWA has install assets, prompts for updates and does not cache API', () => {
  const config = readFileSync('vite.config.ts','utf8')
  assert.match(config,/registerType: 'prompt'/)
  assert.match(config,/navigateFallbackDenylist/)
  assert.doesNotMatch(config,/runtimeCaching/)
  const scripts = JSON.parse(readFileSync('package.json','utf8')).scripts
  for (const name of ['dev','build','preview']) assert.match(scripts[name], /--config vite.config.ts/)
  for (const name of ['pwa-192x192.png','pwa-512x512.png','maskable-icon-512x512.png','apple-touch-icon-180x180.png']) assert.ok(existsSync(`public/${name}`))
  const ui = readFileSync('src/components/PwaStatus.vue','utf8')
  assert.match(ui,/onNeedReload/)
  assert.match(ui,/reloadRequested && !props.blocked/)
  assert.match(ui,/:disable="blocked"/)
})
