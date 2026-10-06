<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { useQuasar } from 'quasar'
import { api, getAccessToken, isNetworkError, setAccessToken, wsUrl, type CurrentUser, type ShiftWorker, type WorkOrder, type WorkOrderStatus } from './api'
import { flushQueue, queueCompletion, queuedCount, queueTransition } from './offline'
import AppShell from './components/AppShell.vue'
import LoginScreen from './components/LoginScreen.vue'
import MetricCard from './components/MetricCard.vue'
import OrderCard from './components/OrderCard.vue'
import CreateOrderDialog from './components/CreateOrderDialog.vue'
import CompletionDialog from './components/CompletionDialog.vue'
import WorkOrderReportDialog from './components/WorkOrderReportDialog.vue'
import ReportsView from './components/ReportsView.vue'

const $q = useQuasar()
const queryClient = useQueryClient()
const createOpen = ref(false)
const completeOpen = ref(false)
const completingOrder = ref<WorkOrder>()
const reportOrder = ref<WorkOrder | null>(null)
const reportOpen = ref(false)
const currentUser = ref<CurrentUser | null>(null)
const role = ref<'master' | 'worker' | 'reports'>('master')
const authenticated = computed(() => currentUser.value !== null)
const realtimeConnected = ref(false)
const browserOnline = ref(navigator.onLine)
const pendingOffline = ref(0)
const filters = reactive({ siteId: null as number | null, equipmentId: null as number | null, assigneeId: null as number | null, priority: null as WorkOrder['priority'] | null })
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
const workerOrders = computed(() => (orders.data.value ?? []).filter(order => order.assignee_id === currentUser.value?.id && !['closed', 'rejected'].includes(order.status)))

const login = useMutation({
  mutationFn: (credentials: { login: string; pin: string }) => api.login(credentials.login, credentials.pin),
  onSuccess: async session => { setAccessToken(session.access_token); currentUser.value = session.user; role.value = session.user.role === 'worker' ? 'worker' : session.user.role === 'manager' ? 'reports' : 'master'; pendingOffline.value = await queuedCount(session.user.id); await syncOffline(); queryClient.invalidateQueries(); connectRealtime() },
  onError: error => $q.notify({ type: 'negative', message: error.message }),
})
function logout(message?: string) {
  setAccessToken(null)
  currentUser.value = null
  queryClient.clear()
  if (socket) { socket.onclose = null; socket.close(); socket = undefined }
  realtimeConnected.value = false
  pendingOffline.value = 0
  if (message) $q.notify({ type: 'warning', message })
}

const createOrder = useMutation({
  mutationFn: ({ data, photos }: { data: Record<string, unknown>; photos: File[] }) => api.createWorkOrder(data, photos),
  onSuccess: order => { queryClient.invalidateQueries({ queryKey: ['work-orders'] }); createOpen.value = false; $q.notify({ type: 'positive', message: `Наряд ${order.number} выдан` }) },
  onError: error => $q.notify({ type: 'negative', message: error.message }),
})
const transition = useMutation({
  mutationFn: async ({ id, status, comment }: { id: number; status: WorkOrderStatus; comment?: string }) => {
    try { return { queued: false, order: await api.transition(id, status, comment) } }
    catch (error) {
      if (!isNetworkError(error) || !currentUser.value) throw error
      await queueTransition(currentUser.value.id, id, status, comment)
      pendingOffline.value = await queuedCount(currentUser.value.id)
      return { queued: true, order: null }
    }
  },
  onSuccess: (result, input) => {
    if (result.queued) {
      queryClient.setQueryData<WorkOrder[]>(['work-orders'], list => list?.map(order => order.id === input.id ? { ...order, status: input.status } : order))
      $q.notify({ type: 'info', icon: 'cloud_off', message: 'Действие сохранено и отправится при появлении сети' })
    } else queryClient.invalidateQueries({ queryKey: ['work-orders'] })
  },
  onError: error => $q.notify({ type: 'negative', message: error.message }),
})
const completeOrder = useMutation({
  mutationFn: async ({ id, data }: { id: number; data: FormData }) => {
    try { return { queued: false, order: await api.complete(id, data) } }
    catch (error) {
      if (!isNetworkError(error) || !currentUser.value) throw error
      await queueCompletion(currentUser.value.id, id, data)
      pendingOffline.value = await queuedCount(currentUser.value.id)
      return { queued: true, order: null }
    }
  },
  onSuccess: (result, input) => {
    completeOpen.value=false
    if (result.queued) {
      queryClient.setQueryData<WorkOrder[]>(['work-orders'], list => list?.map(order => order.id === input.id ? { ...order, status: 'completed' } : order))
      $q.notify({ type: 'info', icon: 'cloud_off', message: 'Отчёт сохранён на устройстве и ожидает сеть' })
    } else {
      queryClient.invalidateQueries({queryKey:['work-orders']})
      $q.notify({type:'positive',message:`Наряд ${result.order!.number} отправлен на проверку`})
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
const counts = computed(() => { const list=orders.data.value??[]; return { total:list.length, active:list.filter(i=>['accepted','in_progress','paused'].includes(i.status)).length, overdue:list.filter(i=>new Date(i.due_at)<new Date()&&i.status!=='closed').length, closed:list.filter(i=>i.status==='closed').length } })
const statusMeta:Record<WorkOrderStatus,{label:string;color:string}>={ issued:{label:'Выдан',color:'blue-grey'}, accepted:{label:'Принят',color:'blue'}, queued:{label:'В очереди',color:'indigo'}, rejected:{label:'Отклонён',color:'negative'}, in_progress:{label:'В работе',color:'amber-9'}, paused:{label:'Приостановлен',color:'orange'}, completed:{label:'Исполнен',color:'teal'}, ai_review:{label:'Проверка ИИ',color:'purple'}, rework:{label:'На доработке',color:'deep-orange'}, closed:{label:'Закрыт',color:'positive'} }
function name(items:Array<{id:number;name?:string;full_name?:string}>|undefined,id:number){const item=items?.find(x=>x.id===id);return item?.name??item?.full_name??`#${id}`}
function isOverdue(order:WorkOrder){return order.status!=='closed'&&new Date(order.due_at)<new Date()}
const visibleOrders = computed(() => (orders.data.value ?? []).filter(order =>
  (filters.siteId === null || order.site_id === filters.siteId) &&
  (filters.equipmentId === null || order.equipment_id === filters.equipmentId) &&
  (filters.assigneeId === null || order.assignee_id === filters.assigneeId) &&
  (filters.priority === null || order.priority === filters.priority),
))
function laneFor(order: WorkOrder) {
  if (isOverdue(order)) return 'overdue'
  if (order.status === 'issued' || order.status === 'rejected') return 'issued'
  if (order.status === 'queued') return 'queued'
  if (['accepted', 'in_progress', 'paused', 'rework'].includes(order.status)) return 'active'
  return 'completed'
}
const masterLanes = computed(() => [
  { key: 'issued', label: 'Выдано' },
  { key: 'queued', label: 'В очереди' },
  { key: 'active', label: 'В работе' },
  { key: 'completed', label: 'Исполнено / проверка' },
  { key: 'overdue', label: 'Просрочено' },
].map(lane => ({ ...lane, orders: visibleOrders.value.filter(order => laneFor(order) === lane.key) })))
const workerStateLabels: Record<ShiftWorker['state'], string> = { free: 'Свободен', busy: 'Занят', queued: 'Есть очередь', off_shift: 'Не на смене' }
function reviewFor(orderId:number){return reviews.data.value?.find(review=>review.work_order_id===orderId)}
function masterDecision(order:WorkOrder,status:'closed'|'rework'){transition.mutate({id:order.id,status,comment:status==='closed'?'Оценка принята мастером':'Возвращено на доработку'})}
function showOrderReport(order: WorkOrder) { reportOrder.value = order; reportOpen.value = true }
function actions(order: WorkOrder): Array<{ label: string; status: WorkOrderStatus; color: string; icon: string }> {
  if (order.status === 'issued') return [{ label:'Принять',status:'accepted',color:'primary',icon:'check' },{ label:'В очередь',status:'queued',color:'indigo',icon:'playlist_add' },{ label:'Отклонить',status:'rejected',color:'negative',icon:'block' }]
  if (order.status === 'queued') return [{ label:'Принять',status:'accepted',color:'primary',icon:'check' }]
  if (order.status === 'accepted') return [{ label:'Начать',status:'in_progress',color:'positive',icon:'play_arrow' }]
  if (order.status === 'in_progress') return [{ label:'Приостановить',status:'paused',color:'warning',icon:'pause' },{ label:'Исполнено',status:'completed',color:'positive',icon:'task_alt' }]
  if (order.status === 'paused') return [{ label:'Продолжить',status:'in_progress',color:'primary',icon:'play_arrow' }]
  if (order.status === 'rework') return [{ label:'В работу',status:'in_progress',color:'deep-orange',icon:'build' }]
  return []
}
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
  socket.onopen = () => { realtimeConnected.value = true }
  socket.onmessage = () => { queryClient.invalidateQueries({ queryKey: ['work-orders'] }); queryClient.invalidateQueries({ queryKey: ['ai-reviews'] }); queryClient.invalidateQueries({queryKey:['notifications']}) }
  socket.onclose = () => { realtimeConnected.value = false; socket = undefined; if (currentUser.value) window.setTimeout(connectRealtime, 2000) }
}
async function syncOffline() {
  browserOnline.value = navigator.onLine
  if (!browserOnline.value || !currentUser.value) return
  const result = await flushQueue(currentUser.value.id)
  pendingOffline.value = result.remaining
  if (result.synced) {
    queryClient.invalidateQueries({ queryKey: ['work-orders'] })
    $q.notify({ type: 'positive', icon: 'cloud_done', message: `Синхронизировано действий: ${result.synced}` })
  }
  if (result.discarded) $q.notify({ type: 'warning', message: `Не удалось применить действий: ${result.discarded}` })
}
async function restoreSession() {
  if (!getAccessToken()) return
  try {
    currentUser.value = await api.me()
    role.value = currentUser.value.role === 'worker' ? 'worker' : currentUser.value.role === 'manager' ? 'reports' : 'master'
    pendingOffline.value = await queuedCount(currentUser.value.id)
    await syncOffline()
    connectRealtime()
  } catch { logout() }
}
function authExpired() { logout('Сессия истекла. Войдите снова.') }
onMounted(() => { restoreSession(); window.addEventListener('naryad-auth-expired', authExpired); window.addEventListener('online', syncOffline); window.addEventListener('offline', syncOffline) })
onBeforeUnmount(() => { window.removeEventListener('naryad-auth-expired', authExpired); window.removeEventListener('online', syncOffline); window.removeEventListener('offline', syncOffline) })
onBeforeUnmount(() => { if (socket) { socket.onclose = null; socket.close() } })
</script>

<template>
  <LoginScreen v-if="!currentUser" :loading="login.isPending.value" @login="(username, pin) => login.mutate({ login: username, pin })" />
  <AppShell v-else v-model:view="role" :user="currentUser" :online="browserOnline && health.isSuccess.value && realtimeConnected" :unread="unreadCount" :pending="pendingOffline" @logout="logout()">
    <template #notifications><q-btn flat round icon="notifications_none" color="grey-7"><q-badge v-if="unreadCount" floating rounded color="negative">{{ unreadCount }}</q-badge><q-menu anchor="bottom right" self="top right"><q-list class="notification-list"><q-item-label header>Уведомления</q-item-label><q-item v-for="item in notifications" :key="item.id" clickable :class="{'unread-notification':!item.is_read}" @click="markRead.mutate(item.id)"><q-item-section avatar><q-icon :name="item.kind==='overdue'?'alarm':item.kind==='unaccepted'?'person_off':'notifications_active'" :color="item.kind==='overdue'?'negative':'primary'"/></q-item-section><q-item-section><q-item-label>{{ item.title }}</q-item-label><q-item-label caption lines="3">{{ item.message }}</q-item-label></q-item-section></q-item><q-item v-if="!notifications.length"><q-item-section class="text-grey-7">Новых уведомлений нет.</q-item-section></q-item></q-list></q-menu></q-btn></template>
    <q-page class="page-shell">
      <template v-if="role==='master'">
        <div class="page-heading"><div><div class="eyebrow">Оперативная панель</div><h1>Текущая смена</h1><p>Контроль работ, сроков и загрузки бригады</p></div><q-btn unelevated no-caps color="primary" icon="add" size="lg" label="Выдать наряд" class="primary-action" @click="createOpen=true"/></div>
        <div class="metrics-grid"><MetricCard label="Всего нарядов" :value="counts.total" icon="assignment" tone="blue"/><MetricCard label="В работе" :value="counts.active" icon="construction" tone="amber"/><MetricCard label="Просрочено" :value="counts.overdue" icon="alarm" tone="red"/><MetricCard label="Закрыто" :value="counts.closed" icon="task_alt" tone="green"/></div>
        <div class="staff-section">
          <div class="section-heading"><div><h2>Исполнители смены</h2><span>{{ shiftWorkers.data.value?.length ?? 0 }} сотрудников</span></div></div>
          <div class="staff-grid">
            <article v-for="worker in shiftWorkers.data.value" :key="worker.id" class="staff-item">
              <div class="staff-item-top"><b>{{ worker.full_name }}</b><q-badge :color="worker.state==='free'?'positive':worker.state==='off_shift'?'grey-6':worker.state==='busy'?'amber-9':'blue'">{{ workerStateLabels[worker.state] }}</q-badge></div>
              <span>{{ worker.specialty ?? 'Специальность не указана' }}</span>
              <small v-if="worker.current_order_number">Выполняет {{ worker.current_order_number }}</small>
              <small v-else-if="worker.queue_count">Нарядов ожидает: {{ worker.queue_count }}</small>
            </article>
          </div>
        </div>
        <div class="section-heading"><div><h2>Наряды смены</h2><span>{{ visibleOrders.length }} записей</span></div><div class="ai-state"><span :class="{ active: aiStatus.data.value?.available }"/><q-icon name="neurology"/> {{ aiStatus.data.value?.available ? 'Локальная AI активна' : 'Резервный режим' }}</div></div>
        <div class="board-filters">
          <q-select v-model="filters.siteId" dense outlined clearable emit-value map-options label="Участок" :options="directories.data.value?.sites.map(site => ({ label: site.name, value: site.id })) ?? []" />
          <q-select v-model="filters.equipmentId" dense outlined clearable emit-value map-options label="Оборудование" :options="directories.data.value?.equipment.map(item => ({ label: item.name, value: item.id })) ?? []" />
          <q-select v-model="filters.assigneeId" dense outlined clearable emit-value map-options label="Исполнитель" :options="directories.data.value?.users.filter(user => user.role==='worker').map(user => ({ label: user.full_name, value: user.id })) ?? []" />
          <q-select v-model="filters.priority" dense outlined clearable emit-value map-options label="Приоритет" :options="[{label:'Аварийный',value:'emergency'},{label:'Высокий',value:'high'},{label:'Обычный',value:'normal'},{label:'Плановый',value:'planned'}]" />
        </div>
        <div class="kanban-board">
          <section v-for="lane in masterLanes" :key="lane.key" class="kanban-lane">
            <header><h3>{{ lane.label }}</h3><q-badge color="grey-4" text-color="dark">{{ lane.orders.length }}</q-badge></header>
            <div class="kanban-orders">
              <OrderCard v-for="order in lane.orders" :key="order.id" compact :order="order" :equipment="name(directories.data.value?.equipment,order.equipment_id)" :assignee="name(directories.data.value?.users,order.assignee_id)" :status-label="statusMeta[order.status].label" :status-color="statusMeta[order.status].color" :overdue="isOverdue(order)" :review="reviewFor(order.id)">
                <template #actions>
                  <q-btn flat no-caps icon="description" label="Отчёт" @click="showOrderReport(order)" />
                  <q-btn v-if="order.status==='completed'" unelevated no-caps color="purple" icon="neurology" label="Запустить проверку" class="full-width" :loading="runReview.isPending.value" @click="runReview.mutate(order.id)" />
                  <template v-if="order.status==='ai_review'"><q-btn outline no-caps color="negative" label="На доработку" class="col" @click="masterDecision(order,'rework')"/><q-btn unelevated no-caps color="positive" label="Принять" class="col" @click="masterDecision(order,'closed')"/></template>
                </template>
              </OrderCard>
              <div v-if="!lane.orders.length" class="kanban-empty">Нет нарядов</div>
            </div>
          </section>
        </div>
      </template>
      <template v-else-if="role==='worker'">
        <div class="page-heading worker-heading"><div><div class="eyebrow">Рабочее место исполнителя</div><h1>Мои наряды</h1><p>{{ workerOrders.length }} активных задач на смену</p></div></div>
        <div class="worker-list"><OrderCard v-for="order in workerOrders" :key="order.id" compact :order="order" :equipment="name(directories.data.value?.equipment,order.equipment_id)" :status-label="statusMeta[order.status].label" :status-color="statusMeta[order.status].color" :overdue="isOverdue(order)" :review="reviewFor(order.id)"><template #actions><q-btn v-for="action in actions(order)" :key="action.status" unelevated no-caps size="lg" class="col" :color="action.color" :icon="action.icon" :label="action.label" :loading="transition.isPending.value" @click="handleAction(order,action.status)"/></template></OrderCard></div>
        <div v-if="!workerOrders.length" class="empty-state"><q-icon name="task_alt"/><h3>Все задачи выполнены</h3><p>Новые наряды появятся здесь автоматически.</p></div>
      </template>
      <template v-else>
        <ReportsView :shift="shiftReport.data.value" :workers="ratings.data.value?.workers" :history="historyAnalytics.data.value"/>
      </template>
    </q-page>
    <CreateOrderDialog v-model="createOpen" :directories="directories.data.value" :loading="createOrder.isPending.value" @submit="createOrder.mutate"/>
    <CompletionDialog v-model="completeOpen" :order="completingOrder" :directories="directories.data.value" :loading="completeOrder.isPending.value" @submit="data => completingOrder && completeOrder.mutate({ id: completingOrder.id, data })"/>
    <WorkOrderReportDialog v-model="reportOpen" :order="reportOrder" />
  </AppShell>
</template>

<style scoped>
.page-shell{min-height:100vh;padding:34px 36px 60px;background:#f2f5f3}.page-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin-bottom:28px}.eyebrow{text-transform:uppercase;letter-spacing:.14em;color:#34805e;font-size:10px;font-weight:800}.page-heading h1{font-size:34px;line-height:1.1;letter-spacing:-.035em;margin:7px 0 5px;color:#18251f}.page-heading p{margin:0;color:#748079;font-size:13px}.primary-action{height:48px;border-radius:11px;padding:0 20px;font-weight:700}.metrics-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin-bottom:32px}.section-heading{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}.section-heading h2{font-size:19px;margin:0;color:#1c2b24}.section-heading>div:first-child{display:flex;align-items:baseline;gap:10px}.section-heading>div:first-child span{font-size:11px;color:#89958f}.ai-state{display:flex;align-items:center;gap:6px;padding:7px 10px;border:1px solid #dce5e0;border-radius:20px;background:#fff;color:#617169;font-size:10px;font-weight:700}.ai-state>span{width:7px;height:7px;border-radius:50%;background:#bdc6c1}.ai-state>span.active{background:#2ab16c;box-shadow:0 0 0 3px rgb(42 177 108/12%)}.order-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:14px}.worker-list{display:grid;gap:14px;max-width:780px}.empty-state{display:grid;place-items:center;text-align:center;min-height:320px;padding:36px;border:1px dashed #cbd7d1;border-radius:18px;background:#f8faf9;color:#718079}.empty-state .q-icon{font-size:54px;color:#59a47d}.empty-state h3{margin:14px 0 3px;color:#283730}.empty-state p{margin:0;font-size:13px}.notification-list{width:min(390px,92vw);max-height:460px}.unread-notification{background:#edf7f1}.create-dialog{width:min(700px,96vw);border-radius:18px}.ratings-card,.pattern-card{border-radius:16px;border-color:#dfe7e3;box-shadow:0 3px 12px rgb(20 52 40/4%)}.ratings-card{max-width:1050px}.pattern-card{border-left-width:4px}.severity-high{border-left-color:#c8443b}.severity-medium{border-left-color:#dda324}@media(max-width:1200px){.metrics-grid{grid-template-columns:repeat(2,1fr)}}@media(max-width:1023px){.page-shell{padding:25px 22px 90px}}@media(max-width:599px){.page-shell{padding:22px 14px 88px}.page-heading{align-items:flex-start}.page-heading h1{font-size:28px}.page-heading p{max-width:230px}.primary-action{width:48px;padding:0;font-size:0}.primary-action :deep(.q-icon){margin:0}.metrics-grid{grid-template-columns:repeat(2,1fr);gap:9px}.order-grid{grid-template-columns:1fr}.section-heading{align-items:flex-start}.ai-state{max-width:155px}.create-dialog{border-radius:16px}.worker-list :deep(.card-actions .q-btn){min-height:50px}}
</style>

<style scoped>
.staff-section{margin:0 0 30px}.staff-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px}.staff-item{display:grid;gap:7px;padding:13px 15px;background:#fff;border:1px solid #dfe7e3;border-radius:8px}.staff-item-top{display:flex;align-items:center;justify-content:space-between;gap:8px}.staff-item-top b{font-size:12px;color:#24332b}.staff-item>span,.staff-item small{font-size:11px;color:#718078}.board-filters{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:10px;margin-bottom:14px}.kanban-board{display:grid;grid-template-columns:repeat(5,minmax(250px,1fr));gap:12px;overflow-x:auto;padding-bottom:8px;align-items:start}.kanban-lane{min-width:250px;padding:10px;background:#e9eeeb;border-radius:8px}.kanban-lane>header{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:2px 2px 10px}.kanban-lane h3{margin:0;color:#34433b;font-size:12px;font-weight:750}.kanban-orders{display:grid;gap:10px}.kanban-empty{padding:18px 10px;text-align:center;color:#89948e;font-size:11px;border:1px dashed #c6d1cb;border-radius:7px;background:rgb(255 255 255/45%)}
@media(max-width:760px){.board-filters{grid-template-columns:repeat(2,minmax(0,1fr))}.kanban-board{grid-template-columns:repeat(5,minmax(265px,1fr));margin-right:-18px;padding-right:18px}}
</style>
