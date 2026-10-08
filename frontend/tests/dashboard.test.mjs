import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { readFileSync, readdirSync } from 'node:fs'
import { createSSRApp, defineComponent, h } from 'vue'
import { renderToString } from 'vue/server-renderer'

// Component rendering checks, not browser/visual acceptance tests.
let server, master, worker, state, presentation
before(async () => {
  server = await createServer({ configFile: false, plugins: [vue()], optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, watch: null }, appType: 'custom' })
  master = (await server.ssrLoadModule('/src/components/MasterDashboard.vue')).default
  worker = (await server.ssrLoadModule('/src/components/WorkerDashboard.vue')).default
  state = (await server.ssrLoadModule('/src/components/DashboardState.vue')).default
  presentation = await server.ssrLoadModule('/src/utils/workOrders.ts')
})
after(() => server?.close())
const order = { id: 1, number: 'TEST-001', description: 'Проверить привод', status: 'issued', priority: 'normal', equipment_id: 1, assignee_id: 1, site_id: 1, due_at: '2099-01-01T00:00:00Z' }
const props = { orders: [order], workers: [], reviews: [], loading: false, offline: false, workersLoading: false, aiAvailable: false, reviewPending: false, decisionPending: false }
async function render(component, properties, mobile = false) {
  const app = createSSRApp(component, properties)
  app.config.globalProperties.$q = { screen: { lt: { md: mobile } } }
  const stub = defineComponent({ setup: (_, { slots, attrs }) => () => h('div', attrs, [attrs.label, ...Object.values(slots).map(slot => slot())]) })
  for (const name of ['btn','badge','icon','select','skeleton','banner']) app.component(`q-${name}`, stub)
  return renderToString(app)
}
test('desktop board renders all five lanes', async () => {
  const html = await render(master, props)
  assert.equal((html.match(/class="kanban-lane"/g) ?? []).length, 5)
  assert.match(html, /TEST-001/)
})
test('completed orders can be accepted or returned without AI', async () => {
  const html = await render(master, { ...props, orders: [{ ...order, status: 'completed' }] })
  assert.match(html, /На доработку/)
  assert.match(html, /Принять/)
})
test('mobile board renders a single selected lane', async () => {
  const html = await render(master, props, true)
  assert.equal((html.match(/class="kanban-lane"/g) ?? []).length, 1)
  assert.match(html, /Колонка нарядов/)
})
test('mobile board initially shows overdue orders instead of an empty issued lane', async () => {
  const html = await render(master, { ...props, orders: [{ ...order, due_at: '2020-01-01T00:00:00Z' }] }, true)
  assert.match(html, /<h3[^>]*>Просрочено<\/h3>/)
  assert.match(html, /TEST-001/)
  assert.equal((html.match(/class="kanban-lane"/g) ?? []).length, 1)
})
test('automatic lane choice preserves manual selection, including an empty lane', () => {
  const lanes = [{ key: 'issued', orders: [] }, { key: 'active', orders: [order] }, { key: 'overdue', orders: [order] }]
  assert.equal(presentation.initialMobileLane(lanes, null), 'overdue')
  assert.equal(presentation.initialMobileLane(lanes, 'issued'), 'issued')
  assert.equal(presentation.initialMobileLane(lanes.slice(0, 2), null), 'active')
  assert.equal(presentation.initialMobileLane([{ key: 'issued', orders: [] }], null), 'issued')
})
test('worker can see report entry and action buttons', async () => {
  const html = await render(worker, { ...props, pending: false })
  assert.match(html, /Отчёт и фото/)
  assert.match(html, /Принять/)
  assert.doesNotMatch(html, /Нет активных нарядов/)
})
test('empty worker screen differs from loading', async () => {
  assert.match(await render(worker, { ...props, orders: [], pending: false }), /Нет активных нарядов/)
  assert.doesNotMatch(await render(worker, { ...props, orders: [], pending: false, loading: true }), /Нет активных нарядов/)
})
test('offline and error messages preserve cached-data distinction', async () => {
  const html = await render(state, { loading: false, offline: true, error: 'Сеть недоступна', hasData: true })
  assert.match(html, /Нет сети/)
  assert.match(html, /Показана последняя версия/)
  assert.match(html, /Повторить/)
})
test('closed orders are never marked overdue and completed have no worker actions', () => {
  assert.equal(presentation.isOverdue({ ...order, status: 'closed', due_at: '2020-01-01' }), false)
  assert.deepEqual(presentation.actions({ ...order, status: 'completed' }), [])
})
test('all Quasar tags used in templates are explicitly registered', () => {
  const main = readFileSync('src/main.ts', 'utf8')
  const registration = main.match(/components: \{([\s\S]*?)\n  \}/)?.[1] ?? ''
  const files = ['src/App.vue', ...readdirSync('src/components').filter(file => file.endsWith('.vue')).map(file => `src/components/${file}`)]
  for (const file of files) {
    for (const [, tag] of readFileSync(file, 'utf8').matchAll(/<(q-[a-z-]+)/g)) {
      const name = tag.split('-').map(part => part[0].toUpperCase() + part.slice(1)).join('')
      assert.match(registration, new RegExp(`\\b${name}\\b`), `${tag} in ${file} is not registered`)
    }
  }
})
test('responsive shell keeps one drawer mounted and controls its layout visibility', () => {
  const shell = readFileSync('src/components/AppShell.vue', 'utf8')
  const drawer = shell.match(/<q-drawer\b[^>]*>/)?.[0]
  assert.ok(drawer, 'shell must contain a drawer')
  assert.doesNotMatch(drawer, /v-(if|show)=/, 'drawer lifecycle must not depend on viewport')
  assert.match(drawer, /:model-value="\$q\.screen\.gt\.sm"/)
  assert.match(drawer, /behavior="desktop"/, 'mobile navigation must not create an overlay drawer')
})
