import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import ts from 'typescript'

const source=readFileSync('src/utils/roles.ts','utf8')
const code=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText
const {initialView,roleLabels,roleOptions}=await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)
test('four roles have explicit labels and correct initial workspaces',()=>{
  assert.equal(initialView('admin'),'admin')
  assert.equal(initialView('manager'),'reports')
  assert.equal(initialView('worker'),'worker')
  assert.equal(initialView('master'),'master')
  assert.equal(roleLabels.admin,'Администратор')
  assert.equal(roleOptions.length,4)
})
test('admin navigation and account panel are gated by actual authenticated role',()=>{
  const shell=readFileSync('src/components/AppShell.vue','utf8')
  const app=readFileSync('src/App.vue','utf8')
  assert.match(shell,/name: 'admin'[\s\S]*?roles: \['admin'\]/)
  assert.match(app,/role==='admin' && currentUser.role==='admin'/)
  assert.match(app,/event.code===4401/)
})
test('account operations are online-only and do not persist PIN or use offline queue',()=>{
  const panel=readFileSync('src/components/AdminUsersView.vue','utf8')
  assert.match(panel,/expected_session_version:user.session_version/)
  assert.match(panel,/form.pin=''/)
  assert.match(panel,/newPin.value=''/)
  assert.match(panel,/editingAccount.value = user \? \{\.\.\.user\}/)
  assert.doesNotMatch(panel,/localStorage|sessionStorage|indexedDB|queueCompletion|queueTransition/)
  assert.match(panel,/if \(!props.online\)/)
})
