import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync, readdirSync } from 'node:fs'
import ts from 'typescript'

function compile(path) {
  return ts.transpileModule(readFileSync(path, 'utf8'), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
  }).outputText
}
const url = code => `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
const preferenceUrl = url(compile('src/utils/themePreference.ts'))
const { parseThemeMode } = await import(preferenceUrl)
test('unknown and missing theme preferences use system mode', () => {
  assert.equal(parseThemeMode('light'), 'light')
  assert.equal(parseThemeMode('dark'), 'dark')
  for (const value of [null, undefined, '', 'system', 'invalid']) assert.equal(parseThemeMode(value), 'system')
})

async function themeFixture(storage, tag) {
  const applied = []
  globalThis.__themeApply = mode => applied.push(mode)
  globalThis.localStorage = storage
  globalThis.window = new EventTarget()
  const darkStub = url('export const Dark = {set: mode => globalThis.__themeApply(mode)}')
  const code = compile('src/theme.ts').replaceAll("'vue'", JSON.stringify(import.meta.resolve('vue'))).replaceAll("'quasar'", JSON.stringify(darkStub)).replaceAll("'./utils/themePreference'", JSON.stringify(preferenceUrl))
  const module = await import(url(`${code}\n// ${tag}`))
  module.initializeTheme()
  return { module, applied }
}
test('saved theme is applied, changes persist, and storage events update it', async () => {
  const previous = { window: globalThis.window, storage: globalThis.localStorage }
  try {
    const writes = []
    const f = await themeFixture({ getItem: () => 'dark', setItem: (key, value) => writes.push([key, value]) }, 'saved')
    assert.deepEqual(f.applied, [true])
    f.module.themeMode.value = 'light'
    assert.equal(f.applied.at(-1), false)
    assert.deepEqual(writes.at(-1), ['naryad_theme', 'light'])
    const event = new Event('storage')
    Object.assign(event, { key: 'naryad_theme', newValue: 'system' })
    window.dispatchEvent(event)
    assert.equal(f.applied.at(-1), 'auto')
  } finally {
    globalThis.window = previous.window
    globalThis.localStorage = previous.storage
    delete globalThis.__themeApply
  }
})
test('theme still switches when browser storage is blocked', async () => {
  const previous = { window: globalThis.window, storage: globalThis.localStorage }
  try {
    const f = await themeFixture({ getItem: () => { throw Error('Blocked') }, setItem: () => { throw Error('Blocked') } }, 'blocked')
    assert.equal(f.applied[0], 'auto')
    f.module.themeMode.value = 'dark'
    assert.equal(f.applied.at(-1), true)
  } finally {
    globalThis.window = previous.window
    globalThis.localStorage = previous.storage
    delete globalThis.__themeApply
  }
})

const css = readFileSync('src/theme.css', 'utf8')
const lightBlock = css.match(/:root\s*\{([^}]+)\}/)[1]
const darkBlock = css.match(/body\.body--dark\s*\{([^}]+)\}/)[1]
const palette = block => Object.fromEntries([...block.matchAll(/(--app-[\w-]+):\s*(#[\da-f]{3,6})/gi)].map(([, name, value]) => [name, value]))
function luminance(hex) {
  const digits = hex.slice(1).length === 3 ? [...hex.slice(1)].map(x => x + x).join('') : hex.slice(1)
  const linear = [0, 2, 4].map(i => parseInt(digits.slice(i, i + 2), 16) / 255).map(c => c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4)
  return linear[0] * .2126 + linear[1] * .7152 + linear[2] * .0722
}
test('base text, secondary text and accent meet 4.5:1 contrast in both palettes', () => {
  for (const colors of [palette(lightBlock), palette(darkBlock)]) {
    for (const foreground of ['--app-text', '--app-muted', '--app-accent']) {
      for (const background of ['--app-page', '--app-surface']) {
        const values = [luminance(colors[foreground]), luminance(colors[background])].sort((a, b) => a - b)
        assert.ok((values[1] + .05) / (values[0] + .05) >= 4.5, `${foreground} on ${background}`)
      }
    }
  }
})
test('every component palette variable is defined', () => {
  const files = ['src/App.vue', ...readdirSync('src/components').filter(file => file.endsWith('.vue')).map(file => `src/components/${file}`)]
  for (const file of files) for (const [, name] of readFileSync(file, 'utf8').matchAll(/var\((--app-[\w-]+)\)/g)) {
    assert.ok(lightBlock.includes(`${name}:`), `${name} missing in light palette`)
    assert.ok(darkBlock.includes(`${name}:`), `${name} missing in dark palette`)
  }
})
