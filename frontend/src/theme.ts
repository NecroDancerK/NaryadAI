import { ref, watch } from 'vue'
import { Dark } from 'quasar'
import { parseThemeMode, type ThemeMode } from './utils/themePreference'

const storageKey = 'naryad_theme'
function savedMode(): ThemeMode {
  try { return parseThemeMode(localStorage.getItem(storageKey)) } catch { return 'system' }
}
export const themeMode = ref<ThemeMode>(savedMode())
export function initializeTheme() {
  watch(themeMode, mode => {
    Dark.set(mode === 'system' ? 'auto' : mode === 'dark')
    try { localStorage.setItem(storageKey, mode) } catch { /* Still works when storage is unavailable. */ }
  }, { immediate: true, flush: 'sync' })
  window.addEventListener('storage', event => {
    if (event.key === storageKey) themeMode.value = parseThemeMode(event.newValue)
  })
}
