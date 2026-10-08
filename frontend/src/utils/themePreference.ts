export type ThemeMode = 'light' | 'dark' | 'system'
export function parseThemeMode(value: unknown): ThemeMode {
  return value === 'light' || value === 'dark' ? value : 'system'
}
