<script setup lang="ts">
import type { CurrentUser } from '../api'
import ThemeSelector from './ThemeSelector.vue'

const props = defineProps<{ user: CurrentUser; view: 'master' | 'worker' | 'reports'; online: boolean; unread: number; pending: number }>()
const emit = defineEmits<{ 'update:view': [view: 'master' | 'worker' | 'reports']; logout: [] }>()

const navigation = [
  { name: 'master' as const, label: 'Диспетчерская', icon: 'space_dashboard', roles: ['master', 'admin'] },
  { name: 'worker' as const, label: 'Мои наряды', icon: 'engineering', roles: ['worker'] },
  { name: 'reports' as const, label: 'Аналитика', icon: 'bar_chart', roles: ['master', 'manager', 'admin'] },
]
</script>

<template>
  <q-layout view="lHh Lpr lFf" class="app-layout">
    <q-header class="topbar">
      <q-toolbar class="topbar-inner">
        <div class="mobile-logo"><q-icon name="precision_manufacturing" /> НарядAI</div>
        <q-badge v-if="pending" rounded color="warning" class="mobile-pending"><q-icon name="cloud_off" class="q-mr-xs"/>{{ pending }}</q-badge>
        <div class="connection"><span :class="['connection-dot', { online }]" />{{ pending ? `Ожидает отправки: ${pending}` : online ? 'Система онлайн' : 'Нет соединения' }}</div>
        <q-space />
        <ThemeSelector />
        <slot name="notifications" />
        <div class="user-summary">
          <q-avatar color="green-1" text-color="primary" icon="person" size="38px" />
          <div><div class="user-name">{{ user.full_name }}</div><div class="user-role">{{ user.specialty ?? (user.role === 'master' ? 'Мастер смены' : 'Руководитель') }}</div></div>
        </div>
        <q-btn flat round icon="logout" color="grey-7" title="Выйти" @click="emit('logout')" />
      </q-toolbar>
    </q-header>

    <!-- Keep one drawer registered with QLayout across breakpoint changes. -->
    <q-drawer :model-value="$q.screen.gt.sm" behavior="desktop" :width="250" class="sidebar">
      <div class="sidebar-brand"><div class="sidebar-logo"><q-icon name="precision_manufacturing" /></div><div><b>НарядAI</b><small>Управление сменой</small></div></div>
      <q-list class="nav-list">
        <q-item v-for="item in navigation.filter(item => item.roles.includes(user.role))" :key="item.name" clickable :active="props.view === item.name" active-class="nav-active" @click="emit('update:view', item.name)">
          <q-item-section avatar><q-icon :name="item.icon" /></q-item-section><q-item-section>{{ item.label }}</q-item-section>
        </q-item>
      </q-list>
      <div class="sidebar-footer"><q-icon name="shield" /><div><b>Защищённый контур</b><small>Локальная обработка данных</small></div></div>
    </q-drawer>

    <q-page-container><slot /></q-page-container>

    <q-footer v-if="$q.screen.lt.md" class="mobile-nav">
      <button v-for="item in navigation.filter(item => item.roles.includes(user.role))" :key="item.name" :class="{ active: props.view === item.name }" @click="emit('update:view', item.name)"><q-icon :name="item.icon" /><span>{{ item.label }}</span></button>
    </q-footer>
  </q-layout>
</template>

<style scoped>
.app-layout{background:var(--app-page);color:var(--app-text)}.topbar{background:var(--app-topbar);color:var(--app-text);border-bottom:1px solid var(--app-border);backdrop-filter:blur(12px)}.topbar-inner{height:72px;padding:0 28px}.connection{display:flex;align-items:center;gap:9px;color:var(--app-muted);font-size:13px}.connection-dot{width:8px;height:8px;border-radius:50%;background:#c0c8c4}.connection-dot.online{background:#28a866;box-shadow:0 0 0 4px rgb(40 168 102/12%)}.user-summary{display:flex;align-items:center;gap:11px;margin:0 12px 0 18px}.user-name{font-weight:700;font-size:13px}.user-role{font-size:11px;color:var(--app-muted)}.mobile-logo{display:none;font-size:18px;font-weight:800;color:var(--app-accent)}.mobile-logo .q-icon{font-size:25px;margin-right:5px}.mobile-pending{display:none;margin-left:10px}.sidebar{background:#0e2921;color:#d8e7e0;border:0}.sidebar-brand{height:72px;display:flex;align-items:center;gap:12px;padding:0 24px;border-bottom:1px solid rgb(255 255 255/8%)}.sidebar-logo{width:38px;height:38px;display:grid;place-items:center;border-radius:11px;background:#38a76d;color:#fff;font-size:22px}.sidebar-brand b{display:block;font-size:18px;color:#fff}.sidebar-brand small{display:block;color:#7da293;font-size:10px;margin-top:1px}.nav-list{padding:20px 12px}.nav-list .q-item{min-height:50px;border-radius:11px;margin-bottom:6px;color:#9bb5aa;font-weight:600}.nav-list .q-item__section--avatar{min-width:42px}.nav-active{background:linear-gradient(90deg,#236947,#2f7955)!important;color:#fff!important}.sidebar-footer{position:absolute;left:18px;right:18px;bottom:22px;display:flex;gap:10px;padding:13px;border:1px solid rgb(255 255 255/9%);border-radius:12px;color:#81ae9a}.sidebar-footer .q-icon{font-size:22px}.sidebar-footer b,.sidebar-footer small{display:block;font-size:10px}.sidebar-footer small{color:#628878;margin-top:2px}.mobile-nav{display:flex;background:var(--app-surface);color:var(--app-muted);border-top:1px solid var(--app-border);padding:5px 8px calc(5px + env(safe-area-inset-bottom))}.mobile-nav button{flex:1;border:0;background:transparent;color:#819087;display:flex;flex-direction:column;align-items:center;gap:2px;font:inherit;font-size:10px;padding:5px}.mobile-nav button .q-icon{font-size:23px}.mobile-nav button.active{color:#147548;font-weight:700}@media(max-width:1023px){.topbar-inner{height:62px;padding:0 14px}.mobile-logo,.mobile-pending{display:block}.connection{display:none}.user-summary>div{display:none}.user-summary{margin-left:8px}.q-page-container{padding-bottom:62px}}
</style>
<style scoped>
/* QDrawer renders a separate content surface with its own default background. */
.app-layout :deep(.q-drawer__content.sidebar){background:#0e2921;color:#d8e7e0}
.mobile-nav button{color:var(--app-muted)}
.mobile-nav button.active{color:var(--app-accent)}
</style>
