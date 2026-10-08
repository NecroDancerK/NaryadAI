<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { useQuasar } from 'quasar'
import { api, getAccessToken, setAccessToken, wsUrl, type CurrentUser, type WorkOrder, type WorkOrderStatus } from './api'
import { flushQueue, queueCompletion, queuedCount, queueTransition, queuedActions, retryQueuedAction, type QueuedAction } from './offline'
import OfflineQueuePanel from './components/OfflineQueuePanel.vue'
import AppShell from './components/AppShell.vue'
import LoginScreen from './components/LoginScreen.vue'
import MasterDashboard from './components/MasterDashboard.vue'
import WorkerDashboard from './components/WorkerDashboard.vue'
import CreateOrderDialog from './components/CreateOrderDialog.vue'
import CompletionDialog from './components/CompletionDialog.vue'
import WorkOrderReportDialog from './components/WorkOrderReportDialog.vue'
import ReportsView from './components/ReportsView.vue'
import PwaStatus from './components/PwaStatus.vue'
import { recoverSession } from './utils/sessionRecovery'

const $q = useQuasar()
const queryClient = useQueryClient()
const createOpen = ref(false)
const completeOpen = ref(false)
const completingOrder = ref<WorkOrder>()
const reportOrder = ref<WorkOrder | null>(null)
const reportOpen = ref(false)
const restoringSession = ref(false)
const sessionNotice = ref('')
const currentUser = ref<CurrentUser | null>(null)
const role = ref<'master' | 'worker' | 'reports'>('master')
const authenticated = computed(() => currentUser.value !== null)
const realtimeConnected = ref(false)
const browserOnline = ref(navigator.onLine)
const pendingOffline = ref(0)
const offlineActions = ref<QueuedAction[]>([])
const syncingOffline = ref(false)
let syncTimer: number | undefined
let socket: WebSocket | undefined
const health = useQuery({ queryKey: ['health'], queryFn: api.health, retry: 1 })
const directories = useQuery({ queryKey: ['directories'], queryFn: api.directories, enabled: authenticated })
const orders = useQuery({ queryKey: ['work-orders'], queryFn: api.workOrders, enabled: authenticated, refetchInterval: 3000 })
const shiftWorkers = useQuery({ queryKey: ['shift-workers'], queryFn: api.shiftWorkers, enabled: computed(() => authenticated.value && role.value === 'master'), refetchInterval: 3000 })
const reviews = useQuery({ queryKey: ['ai-reviews'], queryFn: api.aiReviews, enabled: authenticated })
const aiStatus = useQuery({ queryKey: ['ai-status'], queryFn: api.aiStatus, enabled: authenticated, refetchInterval: 30000 })
const userNotifications = useQuery({ queryKey: ['notifications'], queryFn: api.notifications, enabled: authenticated })
const canViewReports = computed(() => ['master','manager','admin'].includes(currentUser.value?.role ?? ''))
const shiftReport = useQuery({ queryKey: ['shift-report'], queryFn: api.shiftReport, enabled: canViewReports, refetchInterval: 15000 })
const ratings = useQuery({ queryKey: ['ratings'], queryFn: api.ratings, enabled: canViewReports, refetchInterval: 15000 })
const historyAnalytics = useQuery({ queryKey: ['history-analytics'], queryFn: api.historyAnalytics, enabled: canViewReports })
const notifications = computed(() => userNotifications.data.value ?? [])
const unreadCount = computed(() => notifications.value.filter(item => !item.is_read).length)
const displayOrders = computed(() => {
  const blocked = new Set(offlineActions.value.filter(action => action.state === 'conflict').map(action => action.payload.orderId))
  return (orders.data.value ?? []).map(order => {
    if (blocked.has(order.id)) return order
    const pending = offlineActions.value.filter(action => action.payload.orderId === order.id)
    const last = pending[pending.length - 1]
    return last ? { ...order, status: last.kind === 'completion' ? 'completed' as const : last.payload.status } : order
  })
})
const workerOrders = computed(() => displayOrders.value.filter(order => order.assignee_id === currentUser.value?.id && !['closed', 'rejected'].includes(order.status)))

const login = useMutation({
  mutationFn: (credentials: { login: string; pin: string }) => api.login(credentials.login, credentials.pin),
  onSuccess: async session => { setAccessToken(session.access_token); currentUser.value = session.user; role.value = session.user.role === 'worker' ? 'worker' : session.user.role === 'manager' ? 'reports' : 'master'; await syncOffline(); queryClient.invalidateQueries(); connectRealtime() },
  onError: error => $q.notify({ type: 'negative', message: error.message }),
})
function logout(message?: string) {
  sessionNotice.value = ''
  createOpen.value = completeOpen.value = reportOpen.value = false
  reportOrder.value = null
  setAccessToken(null)
  currentUser.value = null
  queryClient.clear()
  if (socket) { socket.onclose = null; socket.close(); socket = undefined }
  realtimeConnected.value = false
  pendingOffline.value = 0
  offlineActions.value = []
  if (message) $q.notify({ type: 'warning', message })
}

const createOrder = useMutation({
  mutationFn: ({ data, photos }: { data: Record<string, unknown>; photos: File[] }) => api.createWorkOrder(data, photos),
  onSuccess: order => { queryClient.invalidateQueries({ queryKey: ['work-orders'] }); createOpen.value = false; $q.notify({ type: 'positive', message: `Наряд ${order.number} выдан` }) },
  onError: error => $q.notify({ type: 'negative', message: error.message }),
})
const transition = useMutation({
  mutationFn: async ({ id, status, comment }: { id: number; status: WorkOrderStatus; comment?: string }) => {
    const userId = currentUser.value?.id
    if (!userId) throw new Error('Войдите в систему')
    const token = getAccessToken()
    const hasPending = await queuedCount(userId)
    if (currentUser.value?.id !== userId || getAccessToken() !== token) throw new Error('Учётная запись изменилась. Повторите действие.')
    const actionId = await queueTransition(userId, id, status, comment)
    if (!hasPending && browserOnline.value) await flushQueue(userId, () => currentUser.value?.id === userId && getAccessToken() === token)
    await refreshOffline(userId)
    const pending = (await queuedActions(userId)).find(action => action.id === actionId)
    if (pending?.state === 'conflict') throw new Error(pending.error)
    return { queued: Boolean(pending) }
  },
  onSuccess: (result, input) => {
    if (result.queued) {
      $q.notify({ type: 'info', icon: 'cloud_off', message: 'Действие сохранено и отправится при появлении сети' })
    } else queryClient.invalidateQueries({ queryKey: ['work-orders'] })
  },
  onError: error => $q.notify({ type: 'negative', message: error.message }),
})
const completeOrder = useMutation({
  mutationFn: async ({ id, userId: ownerId, data, draftRevision }: { id: number; userId:number; data: FormData; draftRevision?:string }) => {
    const userId = currentUser.value?.id
    if (!userId || userId !== ownerId) throw new Error('Войдите в учётную запись автора отчёта')
    const token = getAccessToken()
    const hasPending = await queuedCount(userId)
    if (currentUser.value?.id !== userId || getAccessToken() !== token) throw new Error('Учётная запись изменилась. Повторите действие.')
    const actionId = await queueCompletion(userId, id, data, draftRevision)
    try {
      if (!hasPending && browserOnline.value) await flushQueue(userId, () => currentUser.value?.id === userId && getAccessToken() === token)
      await refreshOffline(userId)
      const pending = (await queuedActions(userId)).find(action => action.id === actionId)
      return { queued: Boolean(pending), conflict: pending?.state === 'conflict' ? pending.error : undefined }
    } catch {
      // The durable handoff already committed. Do not invite a second submission
      // because a later network/queue-display update failed.
      return {queued:true,conflict:undefined}
    }
  },
  onSuccess: (result, input) => {
    if (currentUser.value?.id !== input.userId) return
    completeOpen.value=false
    if (result.conflict) {
      $q.notify({type:'warning',message:`Отчёт сохранён в очереди, но требует разбора: ${result.conflict}`})
    } else if (result.queued) {
      $q.notify({ type: 'info', icon: 'cloud_off', message: 'Отчёт сохранён на устройстве и ожидает сеть' })
    } else {
      queryClient.invalidateQueries({queryKey:['work-orders']})
      $q.notify({type:'positive',message:`Наряд ${orders.data.value?.find(order => order.id === input.id)?.number ?? input.id} отправлен на проверку`})
    }
  },
  onError: error => $q.notify({type:'negative',message:error.message}),
})
const runReview = useMutation({
  mutationFn: (id:number) => api.runAiReview(id),
  onSuccess: review => { queryClient.invalidateQueries({queryKey:['work-orders']}); queryClient.invalidateQueries({queryKey:['ai-reviews']}); $q.notify({type:'positive',message:`Проверка завершена: ${review.score}/100`}) },
  onError: error => $q.notify({type:'negative',message:error.message}),
})
const markRead = useMutation({
  mutationFn: (id:number) => api.readNotification(id),
  onSuccess: () => queryClient.invalidateQueries({queryKey:['notifications']}),
})
function masterDecision(order:WorkOrder,status:'closed'|'rework') {
  const userId = currentUser.value?.id
  const token = getAccessToken()
  $q.dialog({
    title: status === 'rework' ? 'Вернуть на доработку' : 'Принять и закрыть наряд',
    message: status === 'rework' ? 'Опишите, что исполнитель должен исправить.' : `Подтвердите приёмку наряда ${order.number}.`,
    prompt: status === 'rework' ? { model: '', type: 'textarea', isValid: (value: string) => Boolean(value.trim()) && value.length <= 2000 } : undefined,
    cancel: { label: 'Отмена', flat: true }, ok: { label: status === 'rework' ? 'Вернуть' : 'Закрыть наряд' },
  }).onOk((reason?: string) => {
    if (currentUser.value?.id !== userId || getAccessToken() !== token) return
    transition.mutate({id:order.id,status,comment:status === 'rework' ? reason!.trim() : 'Работы приняты мастером'})
  })
}
function showOrderReport(order: WorkOrder) { reportOrder.value = order; reportOpen.value = true }
function handleAction(order: WorkOrder, status: WorkOrderStatus) {
  if (status === 'completed') {
    completingOrder.value = order
    completeOpen.value = true
    return
  }
  if (status === 'rejected') {
    $q.dialog({
      title: `Отклонить наряд ${order.number}`,
      message: 'Укажите причину отказа',
      prompt: { model: '', type: 'text', isValid: value => value.trim().length > 0 },
      cancel: true,
      persistent: true,
    }).onOk((comment: string) => transition.mutate({ id: order.id, status, comment: comment.trim() }))
    return
  }
  transition.mutate({ id: order.id, status, comment: status === 'paused' ? 'Ожидание запчастей' : undefined })
}
function connectRealtime() {
  if (!getAccessToken() || socket) return
  socket = new WebSocket(wsUrl())
  socket.onopen = () => { realtimeConnected.value = true; void syncOffline() }
  socket.onmessage = () => { queryClient.invalidateQueries({ queryKey: ['work-orders'] }); queryClient.invalidateQueries({ queryKey: ['ai-reviews'] }); queryClient.invalidateQueries({queryKey:['notifications']}) }
  socket.onclose = () => { realtimeConnected.value = false; socket = undefined; if (currentUser.value) window.setTimeout(connectRealtime, 2000) }
}
async function refreshOffline(userId: number) {
  const list = await queuedActions(userId)
  if (currentUser.value?.id !== userId) return
  offlineActions.value = list
  pendingOffline.value = list.length
}
async function retryOffline(id: number) {
  const userId = currentUser.value?.id
  if (!userId || syncingOffline.value) return
  try { await retryQueuedAction(userId, id); await syncOffline() }
  catch (error) { $q.notify({ type: 'negative', message: error instanceof Error ? error.message : 'Не удалось обновить очередь' }) }
}
async function syncOffline() {
  browserOnline.value = navigator.onLine
  if (!currentUser.value || syncingOffline.value) return
  const userId = currentUser.value.id
  const token = getAccessToken()
  syncingOffline.value = true
  try {
    await refreshOffline(userId)
    if (!browserOnline.value || !pendingOffline.value) return
    const previousConflicts = offlineActions.value.filter(action => action.state === 'conflict').length
    const result = await flushQueue(userId, () => currentUser.value?.id === userId && getAccessToken() === token)
    if (currentUser.value?.id !== userId || getAccessToken() !== token) return
    await refreshOffline(userId)
    if (result.synced || result.conflicts > previousConflicts) {
      queryClient.invalidateQueries({ queryKey: ['work-orders'] })
      queryClient.invalidateQueries({ queryKey: ['ai-reviews'] })
    }
    if (result.synced) $q.notify({ type: 'positive', icon: 'cloud_done', message: `Синхронизировано действий: ${result.synced}` })
    if (result.conflicts > previousConflicts) $q.notify({ type: 'warning', message: 'Часть действий требует разбора. Отчёты и фото сохранены на устройстве.' })
  } catch (error) {
    $q.notify({ type: 'negative', message: error instanceof Error ? error.message : 'Не удалось прочитать очередь на устройстве' })
  } finally {
    syncingOffline.value = false
  }
}
async function restoreSession() {
  if (!getAccessToken() || restoringSession.value || currentUser.value) return
  if (!navigator.onLine) {
    sessionNotice.value = 'Нет сети. Сессия и очередь сохранены на устройстве. Для входа после запуска нужно соединение с сервером.'
    return
  }
  restoringSession.value = true
  try {
    const result = await recoverSession(() => api.me(AbortSignal.timeout(8000)), getAccessToken)
    if (result.state === 'expired') { logout('Сессия истекла. Войдите снова.'); return }
    if (result.state === 'unavailable') {
      sessionNotice.value = 'Сервер недоступен. Сохранённая сессия не удалена; отправка очереди начнётся после подтверждения входа.'
      return
    }
    if (result.state !== 'confirmed') return
    sessionNotice.value = ''
    currentUser.value = result.user
    role.value = currentUser.value.role === 'worker' ? 'worker' : currentUser.value.role === 'manager' ? 'reports' : 'master'
    await syncOffline()
    connectRealtime()
  } finally { restoringSession.value = false }
}
function onlineChanged() {
  browserOnline.value = navigator.onLine
  if (!currentUser.value && getAccessToken()) void restoreSession()
  else void syncOffline()
}
function authExpired() { logout('Сессия истекла. Войдите снова.') }
onMounted(() => { restoreSession(); syncTimer = window.setInterval(() => { if (pendingOffline.value && navigator.onLine) void syncOffline() }, 15000); window.addEventListener('naryad-auth-expired', authExpired); window.addEventListener('online', onlineChanged); window.addEventListener('offline', syncOffline) })
onBeforeUnmount(() => { window.removeEventListener('naryad-auth-expired', authExpired); window.removeEventListener('online', onlineChanged); window.removeEventListener('offline', syncOffline) })
onBeforeUnmount(() => { window.clearInterval(syncTimer); if (socket) { socket.onclose = null; socket.close() } })
</script>

<template>
  <PwaStatus :blocked="createOpen || completeOpen || reportOpen || syncingOffline || transition.isPending.value || completeOrder.isPending.value || createOrder.isPending.value || runReview.isPending.value || login.isPending.value || restoringSession" />
  <LoginScreen v-if="!currentUser" :loading="login.isPending.value || restoringSession" :notice="sessionNotice" :offline="!browserOnline" @retry="restoreSession" @login="(username, pin) => login.mutate({ login: username, pin })" />
  <AppShell v-else v-model:view="role" :user="currentUser" :online="browserOnline && health.isSuccess.value && realtimeConnected" :unread="unreadCount" :pending="pendingOffline" @logout="logout()">
    <template #notifications><q-btn flat round icon="notifications_none" color="grey-7"><q-badge v-if="unreadCount" floating rounded color="negative">{{ unreadCount }}</q-badge><q-menu anchor="bottom right" self="top right"><q-list class="notification-list"><q-item-label header>Уведомления</q-item-label><q-item v-for="item in notifications" :key="item.id" clickable :class="{'unread-notification':!item.is_read}" @click="markRead.mutate(item.id)"><q-item-section avatar><q-icon :name="item.kind==='overdue'?'alarm':item.kind==='unaccepted'?'person_off':'notifications_active'" :color="item.kind==='overdue'?'negative':'primary'"/></q-item-section><q-item-section><q-item-label>{{ item.title }}</q-item-label><q-item-label caption lines="3">{{ item.message }}</q-item-label></q-item-section></q-item><q-item v-if="!notifications.length"><q-item-section class="text-grey-7">Новых уведомлений нет.</q-item-section></q-item></q-list></q-menu></q-btn></template>
    <q-page class="page-shell">
      <OfflineQueuePanel :actions="offlineActions" :syncing="syncingOffline" :online="browserOnline" @sync="syncOffline" @retry="retryOffline" />
      <MasterDashboard v-if="role==='master'" :orders="displayOrders" :directories="directories.data.value" :workers="shiftWorkers.data.value ?? []" :reviews="reviews.data.value ?? []" :loading="orders.isPending.value" :error="orders.error.value?.message" :offline="!browserOnline" :workers-loading="shiftWorkers.isPending.value" :workers-error="shiftWorkers.error.value?.message" :ai-available="aiStatus.data.value?.available ?? false" :review-pending="runReview.isPending.value" :decision-pending="transition.isPending.value" @create="createOpen=true" @report="showOrderReport" @review="runReview.mutate" @decision="masterDecision" @retry="orders.refetch()" @retry-workers="shiftWorkers.refetch()" />
      <WorkerDashboard v-else-if="role==='worker'" :orders="workerOrders" :directories="directories.data.value" :reviews="reviews.data.value ?? []" :loading="orders.isPending.value" :error="orders.error.value?.message" :offline="!browserOnline" :pending="transition.isPending.value" @action="handleAction" @report="showOrderReport" @retry="orders.refetch()" />
      <template v-else>
        <ReportsView :shift="shiftReport.data.value" :workers="ratings.data.value?.workers" :history="historyAnalytics.data.value"/>
      </template>
    </q-page>
    <CreateOrderDialog v-model="createOpen" :directories="directories.data.value" :loading="createOrder.isPending.value" @submit="createOrder.mutate"/>
    <CompletionDialog v-model="completeOpen" :user-id="currentUser?.id" :order="completingOrder" :directories="directories.data.value" :loading="completeOrder.isPending.value" @submit="input => completeOrder.mutate(input)"/>
    <WorkOrderReportDialog v-model="reportOpen" :order="reportOrder" :can-analyze="browserOnline && ['master','admin'].includes(currentUser?.role ?? '')" />
  </AppShell>
</template>

<style scoped>
.page-shell{min-height:100vh;padding:34px 36px 60px;background:var(--app-page)}.notification-list{width:min(390px,92vw);max-height:460px}.unread-notification{background:var(--app-green-bg)}
@media(max-width:1023px){.page-shell{padding:25px 22px 90px}}
@media(max-width:599px){.page-shell{padding:22px 14px 88px}}
</style>
