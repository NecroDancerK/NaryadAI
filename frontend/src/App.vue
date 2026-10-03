<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { date, useQuasar } from 'quasar'
import { api, wsUrl, type WorkOrder, type WorkOrderStatus } from './api'

const $q = useQuasar()
const queryClient = useQueryClient()
const createOpen = ref(false)
const role = ref<'master' | 'worker'>('master')
const realtimeConnected = ref(false)
let socket: WebSocket | undefined
const health = useQuery({ queryKey: ['health'], queryFn: api.health, retry: 1 })
const directories = useQuery({ queryKey: ['directories'], queryFn: api.directories })
const orders = useQuery({ queryKey: ['work-orders'], queryFn: api.workOrders, refetchInterval: 3000 })
const workerOrders = computed(() => (orders.data.value ?? []).filter(order => order.assignee_id === 2 && !['closed', 'rejected'].includes(order.status)))
const form = reactive({ description: '', work_type: 'unplanned', site_id: 1, equipment_id: 1, assignee_id: 2, priority: 'normal', due_at: date.formatDate(Date.now() + 7200000, 'YYYY-MM-DDTHH:mm') })
const workers = computed(() => directories.data.value?.users.filter(u => u.role === 'worker') ?? [])
const equipment = computed(() => directories.data.value?.equipment.filter(e => e.site_id === form.site_id) ?? [])
watch(() => form.site_id, () => { form.equipment_id = equipment.value[0]?.id ?? 0 })

const createOrder = useMutation({
  mutationFn: () => api.createWorkOrder({ ...form, master_id: 1, due_at: new Date(form.due_at).toISOString() }),
  onSuccess: order => { queryClient.invalidateQueries({ queryKey: ['work-orders'] }); createOpen.value = false; form.description = ''; $q.notify({ type: 'positive', message: `Наряд ${order.number} выдан` }) },
  onError: error => $q.notify({ type: 'negative', message: error.message }),
})
const transition = useMutation({
  mutationFn: ({ id, status, comment }: { id: number; status: WorkOrderStatus; comment?: string }) => api.transition(id, status, comment),
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ['work-orders'] }),
  onError: error => $q.notify({ type: 'negative', message: error.message }),
})
const counts = computed(() => { const list=orders.data.value??[]; return { total:list.length, active:list.filter(i=>['accepted','in_progress','paused'].includes(i.status)).length, overdue:list.filter(i=>new Date(i.due_at)<new Date()&&i.status!=='closed').length, closed:list.filter(i=>i.status==='closed').length } })
const statusMeta:Record<WorkOrderStatus,{label:string;color:string}>={ issued:{label:'Выдан',color:'blue-grey'}, accepted:{label:'Принят',color:'blue'}, queued:{label:'В очереди',color:'indigo'}, rejected:{label:'Отклонён',color:'negative'}, in_progress:{label:'В работе',color:'amber-9'}, paused:{label:'Приостановлен',color:'orange'}, completed:{label:'Исполнен',color:'teal'}, ai_review:{label:'Проверка ИИ',color:'purple'}, rework:{label:'На доработке',color:'deep-orange'}, closed:{label:'Закрыт',color:'positive'} }
function name(items:Array<{id:number;name?:string;full_name?:string}>|undefined,id:number){const item=items?.find(x=>x.id===id);return item?.name??item?.full_name??`#${id}`}
function isOverdue(order:WorkOrder){return order.status!=='closed'&&new Date(order.due_at)<new Date()}
function actions(order: WorkOrder): Array<{ label: string; status: WorkOrderStatus; color: string; icon: string }> {
  if (order.status === 'issued') return [{ label:'Принять',status:'accepted',color:'primary',icon:'check' },{ label:'В очередь',status:'queued',color:'indigo',icon:'playlist_add' }]
  if (order.status === 'queued') return [{ label:'Принять',status:'accepted',color:'primary',icon:'check' }]
  if (order.status === 'accepted') return [{ label:'Начать',status:'in_progress',color:'positive',icon:'play_arrow' }]
  if (order.status === 'in_progress') return [{ label:'Приостановить',status:'paused',color:'warning',icon:'pause' },{ label:'Исполнено',status:'completed',color:'positive',icon:'task_alt' }]
  if (order.status === 'paused') return [{ label:'Продолжить',status:'in_progress',color:'primary',icon:'play_arrow' }]
  if (order.status === 'rework') return [{ label:'В работу',status:'in_progress',color:'deep-orange',icon:'build' }]
  return []
}
function connectRealtime() {
  socket = new WebSocket(wsUrl)
  socket.onopen = () => { realtimeConnected.value = true }
  socket.onmessage = () => queryClient.invalidateQueries({ queryKey: ['work-orders'] })
  socket.onclose = () => { realtimeConnected.value = false; window.setTimeout(connectRealtime, 2000) }
}
onMounted(connectRealtime)
onBeforeUnmount(() => { if (socket) { socket.onclose = null; socket.close() } })
</script>

<template>
  <q-layout view="hHh lpR fFf">
    <q-header class="app-header"><q-toolbar class="q-px-md q-py-sm"><q-avatar color="white" text-color="primary" icon="engineering"/><q-toolbar-title><div class="text-weight-bold">НарядAI</div><div class="text-caption text-green-1">{{ role==='master'?'Панель мастера':'Ахметов Ерлан · Слесарь' }}</div></q-toolbar-title><q-badge rounded :color="health.isSuccess.value&&realtimeConnected?'positive':'warning'">{{ realtimeConnected?'Онлайн':'Подключение…' }}</q-badge></q-toolbar><q-tabs v-model="role" dense active-color="white" indicator-color="amber"><q-tab name="master" icon="dashboard" label="Мастер"/><q-tab name="worker" icon="engineering" label="Исполнитель"/></q-tabs></q-header>
    <q-page-container><q-page class="page q-pa-md q-pa-lg-xl">
      <template v-if="role==='master'">
        <div class="row items-center justify-between q-mb-lg q-col-gutter-md"><div><div class="text-h4 text-weight-bold">Смена</div><div class="text-grey-7">Текущие наряды и загрузка исполнителей</div></div><q-btn unelevated color="primary" icon="add" size="lg" label="Выдать наряд" @click="createOpen=true"/></div>
        <div class="row q-col-gutter-md q-mb-lg"><div v-for="metric in [{label:'Всего',value:counts.total,icon:'assignment',color:'primary'},{label:'В работе',value:counts.active,icon:'construction',color:'warning'},{label:'Просрочено',value:counts.overdue,icon:'alarm',color:'negative'},{label:'Закрыто',value:counts.closed,icon:'task_alt',color:'positive'}]" :key="metric.label" class="col-6 col-md-3"><q-card flat bordered class="metric-card"><q-card-section class="row items-center no-wrap"><q-avatar :color="metric.color" text-color="white" :icon="metric.icon"/><div class="q-ml-md"><div class="text-h5 text-weight-bold">{{ metric.value }}</div><div class="text-grey-7">{{ metric.label }}</div></div></q-card-section></q-card></div></div>
        <div class="text-h6 text-weight-bold q-mb-md">Наряды</div>
        <div v-if="orders.data.value?.length" class="order-grid"><q-card v-for="order in orders.data.value" :key="order.id" flat bordered class="order-card"><q-card-section><div class="row items-start justify-between no-wrap q-gutter-sm"><div><div class="text-subtitle1 text-weight-bold">{{ order.number }}</div><div class="text-caption text-grey-7">{{ name(directories.data.value?.equipment,order.equipment_id) }}</div></div><q-badge :color="statusMeta[order.status].color">{{ statusMeta[order.status].label }}</q-badge></div><div class="text-body1 q-mt-md description">{{ order.description }}</div><q-separator class="q-my-md"/><div class="row items-center text-grey-8 q-mb-sm"><q-icon name="person" class="q-mr-sm"/>{{ name(directories.data.value?.users,order.assignee_id) }}</div><div class="row items-center" :class="isOverdue(order)?'text-negative text-weight-bold':'text-grey-8'"><q-icon name="schedule" class="q-mr-sm"/>до {{ date.formatDate(order.due_at,'DD.MM, HH:mm') }}</div></q-card-section></q-card></div>
      </template>
      <template v-else>
        <div class="q-mb-lg"><div class="text-h4 text-weight-bold">Мои наряды</div><div class="text-grey-7">{{ workerOrders.length }} активных</div></div>
        <div class="worker-list"><q-card v-for="order in workerOrders" :key="order.id" flat bordered class="order-card worker-card" :class="{'emergency-card':order.priority==='emergency'}"><q-card-section><div class="row items-center justify-between"><div class="text-h6 text-weight-bold">{{ order.number }}</div><q-badge :color="statusMeta[order.status].color">{{ statusMeta[order.status].label }}</q-badge></div><div class="text-subtitle1 text-weight-medium q-mt-sm">{{ name(directories.data.value?.equipment,order.equipment_id) }}</div><div class="text-body1 q-mt-md">{{ order.description }}</div><div class="q-mt-md" :class="isOverdue(order)?'text-negative text-weight-bold':'text-grey-8'"><q-icon name="schedule"/> до {{ date.formatDate(order.due_at,'DD.MM, HH:mm') }}</div></q-card-section><q-card-actions class="q-pa-md q-pt-none"><q-btn v-for="action in actions(order)" :key="action.status" unelevated no-caps size="lg" class="col" :color="action.color" :icon="action.icon" :label="action.label" :loading="transition.isPending.value" @click="transition.mutate({id:order.id,status:action.status,comment:action.status==='paused'?'Ожидание запчастей':undefined})"/></q-card-actions></q-card></div>
        <q-banner v-if="!workerOrders.length" rounded class="bg-white text-grey-7">Активных нарядов нет.</q-banner>
      </template>
    </q-page></q-page-container>
    <q-dialog v-model="createOpen" persistent><q-card class="create-dialog"><q-card-section class="row items-center"><div class="text-h6 text-weight-bold">Новый наряд</div><q-space/><q-btn v-close-popup flat round icon="close"/></q-card-section><q-form @submit.prevent="createOrder.mutate()"><q-card-section class="q-pt-none q-gutter-md">
      <q-input v-model="form.description" outlined autogrow label="Что нужно сделать *" :rules="[v=>v.length>=5||'Опишите работу подробнее']"/>
      <div class="row q-col-gutter-md"><q-select v-model="form.site_id" class="col-12 col-sm-6" outlined emit-value map-options label="Участок *" :options="directories.data.value?.sites" option-value="id" option-label="name"/><q-select v-model="form.equipment_id" class="col-12 col-sm-6" outlined emit-value map-options label="Оборудование *" :options="equipment" option-value="id" option-label="name"/></div>
      <q-select v-model="form.assignee_id" outlined emit-value map-options label="Исполнитель *" :options="workers" option-value="id" option-label="full_name"/>
      <div class="row q-col-gutter-md"><q-select v-model="form.priority" class="col-12 col-sm-6" outlined emit-value map-options label="Приоритет" :options="[{label:'Аварийный',value:'emergency'},{label:'Высокий',value:'high'},{label:'Обычный',value:'normal'},{label:'Плановый',value:'planned'}]"/><q-input v-model="form.due_at" class="col-12 col-sm-6" outlined type="datetime-local" label="Срок *"/></div>
    </q-card-section><q-card-actions align="right" class="q-pa-md"><q-btn v-close-popup flat label="Отмена"/><q-btn unelevated color="primary" type="submit" label="Выдать наряд" :loading="createOrder.isPending.value"/></q-card-actions></q-form></q-card></q-dialog>
  </q-layout>
</template>

<style scoped>
.app-header{background:linear-gradient(120deg,#12372a,#245c43)}.page{background:#f3f6f4;min-height:100vh}.metric-card,.order-card{border-radius:16px}.metric-card{min-height:96px}.order-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:16px}.order-card{transition:transform .15s,box-shadow .15s}.order-card:hover{transform:translateY(-2px);box-shadow:0 8px 24px rgb(18 55 42/9%)}.description{min-height:48px}.create-dialog{width:min(680px,96vw);border-radius:20px}.worker-list{display:grid;gap:16px;max-width:720px;margin:auto}.worker-card{border-width:2px}.emergency-card{border-color:#c62828;background:#fffafa}@media(max-width:599px){.page{padding:16px}.order-grid{grid-template-columns:1fr}.worker-card .q-btn{min-height:52px}}
</style>
