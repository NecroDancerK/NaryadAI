<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { date, useQuasar } from 'quasar'
import { api, wsUrl, type WorkOrder, type WorkOrderStatus } from './api'

const $q = useQuasar()
const queryClient = useQueryClient()
const createOpen = ref(false)
const completeOpen = ref(false)
const completingOrder = ref<WorkOrder>()
const role = ref<'master' | 'worker' | 'reports'>('master')
const realtimeConnected = ref(false)
let socket: WebSocket | undefined
const health = useQuery({ queryKey: ['health'], queryFn: api.health, retry: 1 })
const directories = useQuery({ queryKey: ['directories'], queryFn: api.directories })
const orders = useQuery({ queryKey: ['work-orders'], queryFn: api.workOrders, refetchInterval: 3000 })
const reviews = useQuery({ queryKey: ['ai-reviews'], queryFn: api.aiReviews })
const masterNotifications = useQuery({ queryKey: ['notifications', 1], queryFn: () => api.notifications(1) })
const workerNotifications = useQuery({ queryKey: ['notifications', 2], queryFn: () => api.notifications(2) })
const shiftReport = useQuery({ queryKey: ['shift-report'], queryFn: api.shiftReport, refetchInterval: 15000 })
const ratings = useQuery({ queryKey: ['ratings'], queryFn: api.ratings, refetchInterval: 15000 })
const historyAnalytics = useQuery({ queryKey: ['history-analytics'], queryFn: api.historyAnalytics })
const notifications = computed(() => role.value === 'worker' ? workerNotifications.data.value ?? [] : masterNotifications.data.value ?? [])
const unreadCount = computed(() => notifications.value.filter(item => !item.is_read).length)
const workerOrders = computed(() => (orders.data.value ?? []).filter(order => order.assignee_id === 2 && !['closed', 'rejected'].includes(order.status)))
const form = reactive({ description: '', work_type: 'unplanned', site_id: 1, equipment_id: 1, assignee_id: 2, priority: 'normal', due_at: date.formatDate(Date.now() + 7200000, 'YYYY-MM-DDTHH:mm') })
const completionForm = reactive({ work_performed: '', fault_code_id: 1, material_id: null as number | null, quantity: 1, photo: null as File | null, comment: '' })
const materialUsages = ref<Array<{ material_id: number; quantity: number }>>([])
const workers = computed(() => directories.data.value?.users.filter(u => u.role === 'worker') ?? [])
const equipment = computed(() => directories.data.value?.equipment.filter(e => e.site_id === form.site_id) ?? [])
watch(() => form.site_id, () => { form.equipment_id = equipment.value[0]?.id ?? 0 })

const createOrder = useMutation({
  mutationFn: () => api.createWorkOrder({ ...form, master_id: 1, due_at: new Date(form.due_at).toISOString() }),
  onSuccess: order => { queryClient.invalidateQueries({ queryKey: ['work-orders'] }); createOpen.value = false; form.description = ''; $q.notify({ type: 'positive', message: `Наряд ${order.number} выдан` }) },
  onError: error => $q.notify({ type: 'negative', message: error.message }),
})
const transition = useMutation({
  mutationFn: ({ id, status, comment, actorId }: { id: number; status: WorkOrderStatus; comment?: string; actorId?: number }) => api.transition(id, status, comment, actorId),
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ['work-orders'] }),
  onError: error => $q.notify({ type: 'negative', message: error.message }),
})
const completeOrder = useMutation({
  mutationFn: async () => {
    if (!completingOrder.value) throw new Error('Наряд не выбран')
    const data = new FormData()
    data.append('actor_id', '2')
    data.append('work_performed', completionForm.work_performed)
    data.append('fault_code_id', String(completionForm.fault_code_id))
    data.append('materials_json', JSON.stringify(materialUsages.value))
    if (completionForm.comment) data.append('comment', completionForm.comment)
    if (completionForm.photo) data.append('photo', completionForm.photo)
    return api.complete(completingOrder.value.id, data)
  },
  onSuccess: order => { completeOpen.value=false; queryClient.invalidateQueries({queryKey:['work-orders']}); $q.notify({type:'positive',message:`Наряд ${order.number} отправлен на проверку`}) },
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
function reviewFor(orderId:number){return reviews.data.value?.find(review=>review.work_order_id===orderId)}
function masterDecision(order:WorkOrder,status:'closed'|'rework'){transition.mutate({id:order.id,status,actorId:1,comment:status==='closed'?'Оценка принята мастером':'Возвращено на доработку'})}
function actions(order: WorkOrder): Array<{ label: string; status: WorkOrderStatus; color: string; icon: string }> {
  if (order.status === 'issued') return [{ label:'Принять',status:'accepted',color:'primary',icon:'check' },{ label:'В очередь',status:'queued',color:'indigo',icon:'playlist_add' }]
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
    completionForm.work_performed = ''
    completionForm.comment = ''
    completionForm.photo = null
    materialUsages.value = []
    completeOpen.value = true
    return
  }
  transition.mutate({ id: order.id, status, comment: status === 'paused' ? 'Ожидание запчастей' : undefined })
}
function addMaterial() {
  if (!completionForm.material_id || completionForm.quantity <= 0) return
  const existing = materialUsages.value.find(item => item.material_id === completionForm.material_id)
  if (existing) existing.quantity += completionForm.quantity
  else materialUsages.value.push({ material_id: completionForm.material_id, quantity: completionForm.quantity })
  completionForm.material_id = null
  completionForm.quantity = 1
}
function connectRealtime() {
  socket = new WebSocket(wsUrl)
  socket.onopen = () => { realtimeConnected.value = true }
  socket.onmessage = () => { queryClient.invalidateQueries({ queryKey: ['work-orders'] }); queryClient.invalidateQueries({ queryKey: ['ai-reviews'] }); queryClient.invalidateQueries({queryKey:['notifications']}) }
  socket.onclose = () => { realtimeConnected.value = false; window.setTimeout(connectRealtime, 2000) }
}
onMounted(connectRealtime)
onBeforeUnmount(() => { if (socket) { socket.onclose = null; socket.close() } })
</script>

<template>
  <q-layout view="hHh lpR fFf">
    <q-header class="app-header"><q-toolbar class="q-px-md q-py-sm"><q-avatar color="white" text-color="primary" icon="engineering"/><q-toolbar-title><div class="text-weight-bold">НарядAI</div><div class="text-caption text-green-1">{{ role==='master'?'Панель мастера':role==='worker'?'Ахметов Ерлан · Слесарь':'Отчёты смены' }}</div></q-toolbar-title><q-btn flat round icon="notifications" class="q-mr-sm"><q-badge v-if="unreadCount" floating color="negative">{{ unreadCount }}</q-badge><q-menu anchor="bottom right" self="top right"><q-list style="min-width:320px;max-width:420px"><q-item-label header>Уведомления</q-item-label><q-item v-for="item in notifications" :key="item.id" clickable :class="{'bg-blue-1':!item.is_read}" @click="markRead.mutate(item.id)"><q-item-section avatar><q-icon :name="item.kind==='overdue'?'alarm':item.kind==='unaccepted'?'person_off':'notifications_active'" :color="item.kind==='overdue'?'negative':'primary'"/></q-item-section><q-item-section><q-item-label>{{ item.title }}</q-item-label><q-item-label caption lines="3">{{ item.message }}</q-item-label></q-item-section></q-item><q-item v-if="!notifications.length"><q-item-section class="text-grey-7">Новых уведомлений нет</q-item-section></q-item></q-list></q-menu></q-btn><q-badge rounded :color="health.isSuccess.value&&realtimeConnected?'positive':'warning'">{{ realtimeConnected?'Онлайн':'Подключение…' }}</q-badge></q-toolbar><q-tabs v-model="role" dense active-color="white" indicator-color="amber"><q-tab name="master" icon="dashboard" label="Мастер"/><q-tab name="worker" icon="engineering" label="Исполнитель"/><q-tab name="reports" icon="analytics" label="Отчёты"/></q-tabs></q-header>
    <q-page-container><q-page class="page q-pa-md q-pa-lg-xl">
      <template v-if="role==='master'">
        <div class="row items-center justify-between q-mb-lg q-col-gutter-md"><div><div class="text-h4 text-weight-bold">Смена</div><div class="text-grey-7">Текущие наряды и загрузка исполнителей</div></div><q-btn unelevated color="primary" icon="add" size="lg" label="Выдать наряд" @click="createOpen=true"/></div>
        <div class="row q-col-gutter-md q-mb-lg"><div v-for="metric in [{label:'Всего',value:counts.total,icon:'assignment',color:'primary'},{label:'В работе',value:counts.active,icon:'construction',color:'warning'},{label:'Просрочено',value:counts.overdue,icon:'alarm',color:'negative'},{label:'Закрыто',value:counts.closed,icon:'task_alt',color:'positive'}]" :key="metric.label" class="col-6 col-md-3"><q-card flat bordered class="metric-card"><q-card-section class="row items-center no-wrap"><q-avatar :color="metric.color" text-color="white" :icon="metric.icon"/><div class="q-ml-md"><div class="text-h5 text-weight-bold">{{ metric.value }}</div><div class="text-grey-7">{{ metric.label }}</div></div></q-card-section></q-card></div></div>
        <div class="text-h6 text-weight-bold q-mb-md">Наряды</div>
        <div v-if="orders.data.value?.length" class="order-grid"><q-card v-for="order in orders.data.value" :key="order.id" flat bordered class="order-card"><q-card-section><div class="row items-start justify-between no-wrap q-gutter-sm"><div><div class="text-subtitle1 text-weight-bold">{{ order.number }}</div><div class="text-caption text-grey-7">{{ name(directories.data.value?.equipment,order.equipment_id) }}</div></div><q-badge :color="statusMeta[order.status].color">{{ statusMeta[order.status].label }}</q-badge></div><div class="text-body1 q-mt-md description">{{ order.description }}</div><q-separator class="q-my-md"/><div class="row items-center text-grey-8 q-mb-sm"><q-icon name="person" class="q-mr-sm"/>{{ name(directories.data.value?.users,order.assignee_id) }}</div><div class="row items-center" :class="isOverdue(order)?'text-negative text-weight-bold':'text-grey-8'"><q-icon name="schedule" class="q-mr-sm"/>до {{ date.formatDate(order.due_at,'DD.MM, HH:mm') }}</div><div v-if="reviewFor(order.id)" class="review-box q-mt-md"><div class="row items-center justify-between"><span class="text-weight-bold">Проверка ИИ</span><q-badge :color="reviewFor(order.id)?.verdict==='rework'?'negative':reviewFor(order.id)?.verdict==='accepted'?'positive':'warning'">{{ reviewFor(order.id)?.score }}/100</q-badge></div><div class="text-caption q-mt-xs">{{ reviewFor(order.id)?.explanation }}</div></div></q-card-section><q-card-actions v-if="order.status==='completed'" class="q-pa-md q-pt-none"><q-btn unelevated color="purple" icon="smart_toy" label="Проверить" class="full-width" :loading="runReview.isPending.value" @click="runReview.mutate(order.id)"/></q-card-actions><q-card-actions v-if="order.status==='ai_review'" class="q-pa-md q-pt-none"><q-btn outline color="negative" label="На доработку" @click="masterDecision(order,'rework')"/><q-btn unelevated color="positive" label="Принять" @click="masterDecision(order,'closed')"/></q-card-actions></q-card></div>
      </template>
      <template v-else-if="role==='worker'">
        <div class="q-mb-lg"><div class="text-h4 text-weight-bold">Мои наряды</div><div class="text-grey-7">{{ workerOrders.length }} активных</div></div>
        <div class="worker-list"><q-card v-for="order in workerOrders" :key="order.id" flat bordered class="order-card worker-card" :class="{'emergency-card':order.priority==='emergency'}"><q-card-section><div class="row items-center justify-between"><div class="text-h6 text-weight-bold">{{ order.number }}</div><q-badge :color="statusMeta[order.status].color">{{ statusMeta[order.status].label }}</q-badge></div><div class="text-subtitle1 text-weight-medium q-mt-sm">{{ name(directories.data.value?.equipment,order.equipment_id) }}</div><div class="text-body1 q-mt-md">{{ order.description }}</div><div class="q-mt-md" :class="isOverdue(order)?'text-negative text-weight-bold':'text-grey-8'"><q-icon name="schedule"/> до {{ date.formatDate(order.due_at,'DD.MM, HH:mm') }}</div></q-card-section><q-card-actions class="q-pa-md q-pt-none"><q-btn v-for="action in actions(order)" :key="action.status" unelevated no-caps size="lg" class="col" :color="action.color" :icon="action.icon" :label="action.label" :loading="transition.isPending.value" @click="handleAction(order,action.status)"/></q-card-actions></q-card></div>
        <q-banner v-if="!workerOrders.length" rounded class="bg-white text-grey-7">Активных нарядов нет.</q-banner>
      </template>
      <template v-else>
        <div class="q-mb-lg"><div class="text-h4 text-weight-bold">Отчёт за смену</div><div class="text-grey-7">Показатели рассчитаны по журналу событий</div></div>
        <div class="row q-col-gutter-md q-mb-xl"><div v-for="metric in [{label:'Выдано',value:shiftReport.data.value?.issued??0,color:'primary',icon:'assignment'},{label:'Выполнено',value:shiftReport.data.value?.completed??0,color:'positive',icon:'task_alt'},{label:'В работе',value:shiftReport.data.value?.active??0,color:'warning',icon:'construction'},{label:'Просрочено',value:shiftReport.data.value?.overdue??0,color:'negative',icon:'alarm'}]" :key="metric.label" class="col-6 col-md-3"><q-card flat bordered class="metric-card"><q-card-section class="row items-center"><q-avatar :color="metric.color" text-color="white" :icon="metric.icon"/><div class="q-ml-md"><div class="text-h5 text-weight-bold">{{ metric.value }}</div><div class="text-grey-7">{{ metric.label }}</div></div></q-card-section></q-card></div></div>
        <q-card flat bordered class="ratings-card"><q-card-section><div class="text-h6 text-weight-bold">Рейтинг исполнителей</div><div class="text-caption text-grey-7">Качество 35% · сроки 25% · надёжность 15% · объём 15% · дисциплина 10%</div></q-card-section><q-separator/><q-list separator><q-item v-for="(worker,index) in ratings.data.value?.workers" :key="worker.worker_id" class="q-py-md"><q-item-section avatar><q-avatar :color="index===0&&worker.score>0?'amber':'blue-grey-2'" :text-color="index===0&&worker.score>0?'brown':'grey-8'">{{ index+1 }}</q-avatar></q-item-section><q-item-section><q-item-label class="text-weight-bold">{{ worker.full_name }}</q-item-label><q-item-label caption>{{ worker.specialty }} · {{ worker.completed }} выполнено из {{ worker.assigned }}</q-item-label><div class="q-mt-sm"><q-linear-progress rounded size="8px" :value="worker.score/100" color="primary" track-color="grey-3"/></div><div class="row q-col-gutter-sm text-caption text-grey-7 q-mt-xs"><div class="col">Качество {{ worker.components.quality }}</div><div class="col">Сроки {{ worker.components.timeliness }}</div><div class="col">Надёжность {{ worker.components.reliability }}</div></div></q-item-section><q-item-section side><div class="text-h5 text-weight-bold text-primary">{{ worker.score }}</div><div class="text-caption">из 100</div></q-item-section></q-item></q-list></q-card>
        <q-card flat bordered class="ratings-card q-mt-lg"><q-card-section><div class="text-h6 text-weight-bold">Дополнительные показатели</div><div class="row q-col-gutter-lg q-mt-sm"><div class="col-12 col-sm-4"><div class="text-caption text-grey-7">Среднее время реакции</div><div class="text-h6">{{ shiftReport.data.value?.average_response_minutes??'—' }} мин</div></div><div class="col-12 col-sm-4"><div class="text-caption text-grey-7">Отклонено</div><div class="text-h6">{{ shiftReport.data.value?.rejected??0 }}</div></div><div class="col-12 col-sm-4"><div class="text-caption text-grey-7">Закрыто мастером</div><div class="text-h6">{{ shiftReport.data.value?.closed??0 }}</div></div></div></q-card-section></q-card>
        <div class="text-h5 text-weight-bold q-mt-xl q-mb-md">Аналитика за 90 дней</div>
        <div class="row q-col-gutter-md"><div v-for="pattern in historyAnalytics.data.value?.patterns" :key="pattern.kind" class="col-12 col-md-4"><q-card flat bordered class="pattern-card full-height" :class="`severity-${pattern.severity}`"><q-card-section><div class="row items-center q-gutter-sm"><q-icon :name="pattern.kind==='problem_equipment'?'precision_manufacturing':pattern.kind==='repeated_fault'?'repeat':'inventory_2'" size="28px" :color="pattern.severity==='high'?'negative':'warning'"/><div class="text-subtitle1 text-weight-bold">{{ pattern.title }}</div></div><div class="text-body2 q-mt-md">{{ pattern.evidence }}</div><q-separator class="q-my-md"/><div class="text-caption text-grey-8"><b>Рекомендация:</b> {{ pattern.recommendation }}</div></q-card-section></q-card></div></div>
        <q-card flat bordered class="ratings-card q-mt-lg"><q-card-section><div class="text-h6 text-weight-bold">Проблемное оборудование</div><div class="text-caption text-grey-7">Проанализировано {{ historyAnalytics.data.value?.orders_analyzed??0 }} нарядов</div></q-card-section><q-markup-table flat><thead><tr><th class="text-left">Оборудование</th><th class="text-right">Отказы</th><th class="text-right">Простой, ч</th></tr></thead><tbody><tr v-for="item in historyAnalytics.data.value?.top_equipment.slice(0,5)" :key="item.equipment_id"><td>{{ item.name }}</td><td class="text-right text-weight-bold">{{ item.unplanned_failures }}</td><td class="text-right">{{ item.downtime_hours }}</td></tr></tbody></q-markup-table></q-card>
        <q-card v-if="historyAnalytics.data.value?.material_anomalies.length" flat bordered class="ratings-card q-mt-lg"><q-card-section><div class="text-h6 text-weight-bold">Аномальные списания</div></q-card-section><q-list separator><q-item v-for="item in historyAnalytics.data.value?.material_anomalies" :key="item.work_order"><q-item-section><q-item-label>{{ item.work_order }} · {{ item.material }}</q-item-label><q-item-label caption>Обычно {{ item.average }}, списано {{ item.quantity }}</q-item-label></q-item-section><q-item-section side><q-badge color="negative">×{{ item.deviation_factor }}</q-badge></q-item-section></q-item></q-list></q-card>
      </template>
    </q-page></q-page-container>
    <q-dialog v-model="createOpen" persistent><q-card class="create-dialog"><q-card-section class="row items-center"><div class="text-h6 text-weight-bold">Новый наряд</div><q-space/><q-btn v-close-popup flat round icon="close"/></q-card-section><q-form @submit.prevent="createOrder.mutate()"><q-card-section class="q-pt-none q-gutter-md">
      <q-input v-model="form.description" outlined autogrow label="Что нужно сделать *" :rules="[v=>v.length>=5||'Опишите работу подробнее']"/>
      <div class="row q-col-gutter-md"><q-select v-model="form.site_id" class="col-12 col-sm-6" outlined emit-value map-options label="Участок *" :options="directories.data.value?.sites" option-value="id" option-label="name"/><q-select v-model="form.equipment_id" class="col-12 col-sm-6" outlined emit-value map-options label="Оборудование *" :options="equipment" option-value="id" option-label="name"/></div>
      <q-select v-model="form.assignee_id" outlined emit-value map-options label="Исполнитель *" :options="workers" option-value="id" option-label="full_name"/>
      <div class="row q-col-gutter-md"><q-select v-model="form.priority" class="col-12 col-sm-6" outlined emit-value map-options label="Приоритет" :options="[{label:'Аварийный',value:'emergency'},{label:'Высокий',value:'high'},{label:'Обычный',value:'normal'},{label:'Плановый',value:'planned'}]"/><q-input v-model="form.due_at" class="col-12 col-sm-6" outlined type="datetime-local" label="Срок *"/></div>
    </q-card-section><q-card-actions align="right" class="q-pa-md"><q-btn v-close-popup flat label="Отмена"/><q-btn unelevated color="primary" type="submit" label="Выдать наряд" :loading="createOrder.isPending.value"/></q-card-actions></q-form></q-card></q-dialog>
    <q-dialog v-model="completeOpen" persistent><q-card class="create-dialog"><q-card-section class="row items-center"><div><div class="text-h6 text-weight-bold">Закрытие {{ completingOrder?.number }}</div><div class="text-caption text-grey-7">Заполните результат выполненных работ</div></div><q-space/><q-btn v-close-popup flat round icon="close"/></q-card-section><q-form @submit.prevent="completeOrder.mutate()"><q-card-section class="q-pt-none q-gutter-md">
      <q-input v-model="completionForm.work_performed" outlined autogrow label="Выполненные работы *" :rules="[v=>v.length>=5||'Опишите выполненные работы']"/>
      <q-select v-model="completionForm.fault_code_id" outlined emit-value map-options label="Шифр неисправности *" :options="directories.data.value?.fault_codes" option-value="id" :option-label="item=>`${item.code} — ${item.name}`"/>
      <div class="text-subtitle2">Списанные материалы</div><div class="row q-col-gutter-sm"><q-select v-model="completionForm.material_id" class="col" outlined dense emit-value map-options clearable label="Материал" :options="directories.data.value?.materials" option-value="id" :option-label="item=>`${item.name}, ${item.unit}`"/><q-input v-model.number="completionForm.quantity" class="col-3" outlined dense type="number" min="0.001" step="0.001" label="Кол-во"/><div class="col-auto"><q-btn round color="primary" icon="add" @click="addMaterial"/></div></div>
      <q-list v-if="materialUsages.length" bordered separator class="rounded-borders"><q-item v-for="(usage,index) in materialUsages" :key="usage.material_id"><q-item-section>{{ name(directories.data.value?.materials,usage.material_id) }}</q-item-section><q-item-section side>{{ usage.quantity }}</q-item-section><q-item-section side><q-btn flat round dense icon="delete" color="negative" @click="materialUsages.splice(index,1)"/></q-item-section></q-item></q-list>
      <q-file v-model="completionForm.photo" outlined accept="image/*" capture="environment" label="Фото после ремонта *" max-file-size="10485760"><template #prepend><q-icon name="photo_camera"/></template></q-file>
      <q-input v-model="completionForm.comment" outlined autogrow label="Комментарий"/>
      <q-banner dense rounded class="bg-blue-1 text-primary"><q-icon name="info"/> После отправки наряд перейдёт на проверку выполнения.</q-banner>
    </q-card-section><q-card-actions align="right" class="q-pa-md"><q-btn v-close-popup flat label="Отмена"/><q-btn unelevated color="positive" type="submit" icon="task_alt" label="Отправить на проверку" :loading="completeOrder.isPending.value"/></q-card-actions></q-form></q-card></q-dialog>
  </q-layout>
</template>

<style scoped>
.app-header{background:linear-gradient(120deg,#12372a,#245c43)}.page{background:#f3f6f4;min-height:100vh}.metric-card,.order-card,.ratings-card,.pattern-card{border-radius:16px}.metric-card{min-height:96px}.ratings-card{max-width:960px}.pattern-card{border-left-width:4px}.severity-high{border-left-color:#c62828}.severity-medium{border-left-color:#f9a825}.order-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:16px}.order-card{transition:transform .15s,box-shadow .15s}.order-card:hover{transform:translateY(-2px);box-shadow:0 8px 24px rgb(18 55 42/9%)}.description{min-height:48px}.create-dialog{width:min(680px,96vw);border-radius:20px}.worker-list{display:grid;gap:16px;max-width:720px;margin:auto}.worker-card{border-width:2px}.emergency-card{border-color:#c62828;background:#fffafa}.review-box{padding:10px;border-radius:10px;background:#f3e5f5;color:#4a148c}@media(max-width:599px){.page{padding:16px}.order-grid{grid-template-columns:1fr}.worker-card .q-btn{min-height:52px}}
</style>
