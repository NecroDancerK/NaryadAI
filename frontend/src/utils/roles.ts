import type { UserRole } from '../api'

export const roleLabels:Record<UserRole,string> = {
  master:'Мастер смены', worker:'Исполнитель', manager:'Руководитель', admin:'Администратор',
}
export const roleOptions = Object.entries(roleLabels).map(([value,label]) => ({value:value as UserRole,label}))
export type AppView = 'master' | 'worker' | 'reports' | 'admin'
export function initialView(role:UserRole):AppView {
  return role === 'worker' ? 'worker' : role === 'manager' ? 'reports' : role === 'admin' ? 'admin' : 'master'
}
