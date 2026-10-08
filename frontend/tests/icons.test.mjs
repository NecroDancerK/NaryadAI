import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

const available = new Set(JSON.parse(readFileSync('node_modules/@quasar/extras/material-icons/icons.json', 'utf8')))
const exportName = name => 'mat' + name.split('_').map(part => part[0].toUpperCase() + part.slice(1)).join('')
function vueFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const path = join(dir, entry.name)
    return entry.isDirectory() ? vueFiles(path) : path.endsWith('.vue') ? [path] : []
  })
}

test('static component and navigation icons exist in the bundled Material Icons set', () => {
  let checked = 0
  for (const path of vueFiles('src')) {
    const source = readFileSync(path, 'utf8')
    const names = [...source.matchAll(/<(q-icon|q-btn|q-avatar|MetricCard)\b[^>]*>/g)].flatMap(([tag, component]) => {
      const attribute = component === 'q-icon' ? /\sname="([a-z0-9_]+)"/g : /\sicon(?:-right)?="([a-z0-9_]+)"/g
      return [...tag.matchAll(attribute)].map(match => match[1])
    })
    names.push(...[...source.matchAll(/\bicon:\s*'([a-z0-9_]+)'/g)].map(match => match[1]))
    for (const name of names) {
      assert.ok(available.has(exportName(name)), `${path}: icon ${name} is not bundled`)
      checked++
    }
  }
  assert.ok(checked > 40, 'Scan should cover the application, not only a single view')
})
