<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import type { WorkOrder, Directories, ShiftWorker, AiInspection } from '../api'
import { statusMeta, name, isOverdue, initialMobileLane } from '../utils/workOrders'
import OrderCard from './OrderCard.vue'
import MetricCard from './MetricCard.vue'
import DashboardState from './DashboardState.vue'
const props = defineProps<{ orders: WorkOrder[]; directories?: Directories; workers: ShiftWorker[]; reviews: AiInspection[]; loading: boolean; error?: string; offline: boolean; workersLoading: boolean; workersError?: string; aiAvailable: boolean; reviewPending: boolean; decisionPending: boolean }>()
const emit = defineEmits<{ create: []; report: [order: WorkOrder]; review: [id: number]; decision: [order: WorkOrder, status: 'closed'|'rework']; retry: []; retryWorkers: [] }>()
const $q = useQuasar()
const filters = reactive({siteId: null as number|null, equipmentId: null as number|null, assigneeId: null as number|null, priority: null as WorkOrder['priority']|null})
watch(() => filters.siteId, () => { filters.equipmentId = null })
const counts = computed(() => { const list=props.orders; return { total:list.length, active:list.filter(i=>['accepted','in_progress','paused'].includes(i.status)).length, overdue:list.filter(i=>new Date(i.due_at)<new Date()&&i.status!=='closed').length, closed:list.filter(i=>i.status==='closed').length } })
const visibleOrders = computed(() => (props.orders).filter(order =>
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
function reviewFor(orderId:number){return props.reviews?.find(review=>review.work_order_id===orderId)}

const selectedMobileLane = ref<string | null>(null)
const mobileLane = computed({
  get: () => initialMobileLane(masterLanes.value, selectedMobileLane.value),
  set: (value: string) => { selectedMobileLane.value = value },
})
const displayedLanes = computed(() => $q.screen.lt.md ? masterLanes.value.filter(lane => lane.key === mobileLane.value) : masterLanes.value)
</script>
<template>
<div>
        <div class="page-heading"><div><div class="eyebrow">Оперативная панель</div><h1>Текущая смена</h1><p>Контроль работ, сроков и загрузки бригады</p></div><q-btn unelevated no-caps color="primary" icon="add" size="lg" label="Выдать наряд" class="primary-action" :disable="offline || !directories" @click="emit('create')"/></div>
        <DashboardState :loading="loading" :error="error" :offline="offline" :has-data="orders.length > 0" @retry="emit('retry')" />
        <div v-if="!loading || orders.length" class="metrics-grid"><MetricCard label="Всего нарядов" :value="counts.total" icon="assignment" tone="blue"/><MetricCard label="В работе" :value="counts.active" icon="construction" tone="amber"/><MetricCard label="Просрочено" :value="counts.overdue" icon="alarm" tone="red"/><MetricCard label="Закрыто" :value="counts.closed" icon="task_alt" tone="green"/></div>
        <div class="staff-section">
          <div class="section-heading"><div><h2>Исполнители смены</h2><span>{{ workers?.length ?? 0 }} сотрудников</span></div></div>
          <DashboardState :loading="workersLoading" :error="workersError" :has-data="workers.length > 0" @retry="emit('retryWorkers')" />
          <p v-if="!workersLoading && !workersError && !workers.length" class="kanban-empty">В смене пока нет исполнителей</p>
          <div class="staff-grid">
            <article v-for="worker in workers" :key="worker.id" class="staff-item">
              <div class="staff-item-top"><b>{{ worker.full_name }}</b><q-badge :color="worker.state==='free'?'positive':worker.state==='off_shift'?'grey-6':worker.state==='busy'?'amber-9':'blue'">{{ workerStateLabels[worker.state] }}</q-badge></div>
              <span>{{ worker.specialty ?? 'Специальность не указана' }}</span>
              <small v-if="worker.current_order_number">Выполняет {{ worker.current_order_number }}</small>
              <small v-else-if="worker.queue_count">Нарядов ожидает: {{ worker.queue_count }}</small>
            </article>
          </div>
        </div>
        <div class="section-heading"><div><h2>Наряды смены</h2><span>{{ visibleOrders.length }} записей</span></div><div class="ai-state"><span :class="{ active: aiAvailable }"/><q-icon name="neurology"/> {{ aiAvailable ? 'Локальная AI активна' : 'Резервный режим' }}</div></div>
        <div class="board-filters">
          <q-select v-model="filters.siteId" dense outlined clearable emit-value map-options label="Участок" :options="directories?.sites.map(site => ({ label: site.name, value: site.id })) ?? []" />
          <q-select v-model="filters.equipmentId" dense outlined clearable emit-value map-options label="Оборудование" :options="directories?.equipment.filter(item => filters.siteId === null || item.site_id === filters.siteId).map(item => ({ label: item.name, value: item.id })) ?? []" />
          <q-select v-model="filters.assigneeId" dense outlined clearable emit-value map-options label="Исполнитель" :options="directories?.users.filter(user => user.role==='worker').map(user => ({ label: user.full_name, value: user.id })) ?? []" />
          <q-select v-model="filters.priority" dense outlined clearable emit-value map-options label="Приоритет" :options="[{label:'Аварийный',value:'emergency'},{label:'Высокий',value:'high'},{label:'Обычный',value:'normal'},{label:'Плановый',value:'planned'}]" />
        </div>
        <q-select v-model="mobileLane" class="mobile-lane-select" outlined emit-value map-options label="Колонка нарядов" :options="masterLanes.map(lane => ({label: lane.label + ' · ' + lane.orders.length, value: lane.key}))" />
        <div v-if="!loading && !error && !orders.length" class="kanban-empty">Нарядов пока нет. Выдайте первый наряд исполнителю.</div>
        <div v-if="!loading || orders.length" class="kanban-board">
          <section v-for="lane in displayedLanes" :key="lane.key" class="kanban-lane">
            <header><h3>{{ lane.label }}</h3><q-badge color="grey-4" text-color="dark">{{ lane.orders.length }}</q-badge></header>
            <div class="kanban-orders">
              <OrderCard v-for="order in lane.orders" :key="order.id" compact :order="order" :equipment="name(directories?.equipment,order.equipment_id)" :assignee="name(directories?.users,order.assignee_id)" :status-label="statusMeta[order.status].label" :status-color="statusMeta[order.status].color" :overdue="isOverdue(order)" :review="reviewFor(order.id)">
                <template #actions>
                  <q-btn flat no-caps icon="description" label="Отчёт" @click="emit('report', order)" />
                  <q-btn v-if="order.status==='completed'" unelevated no-caps color="purple" icon="neurology" label="Запустить проверку" class="full-width" :loading="reviewPending" :disable="offline" @click="emit('review', order.id)" />
                  <template v-if="['completed','ai_review'].includes(order.status)"><q-btn outline no-caps color="negative" label="На доработку" class="col" :disable="offline || decisionPending" @click="emit('decision', order, 'rework')"/><q-btn unelevated no-caps color="positive" label="Принять" class="col" :disable="offline || decisionPending" @click="emit('decision', order, 'closed')"/></template>
                </template>
              </OrderCard>
              <div v-if="!lane.orders.length" class="kanban-empty">Нет нарядов</div>
            </div>
          </section>
        </div>

</div>
</template>
<style scoped>
.page-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin-bottom:28px}
.eyebrow{text-transform:uppercase;letter-spacing:.14em;color:var(--app-accent);font-size:10px;font-weight:800}
h1{font-size:34px;line-height:1.1;letter-spacing:-.035em;margin:7px 0 5px;color:var(--app-text)}
.page-heading p{margin:0;color:var(--app-muted);font-size:13px}
.primary-action{height:48px;border-radius:11px;padding:0 20px;font-weight:700}
.metrics-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin-bottom:32px}
.section-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px}
h2{font-size:19px;margin:0;color:var(--app-text)}
.section-heading>div:first-child{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.section-heading>div:first-child span{font-size:11px;color:var(--app-muted)}
.ai-state{display:flex;align-items:center;gap:6px;padding:7px 10px;border:1px solid var(--app-border);border-radius:20px;background:var(--app-surface);color:var(--app-muted);font-size:10px;font-weight:700}
.ai-state>span{width:7px;height:7px;flex-shrink:0;border-radius:50%;background:#bdc6c1}
.ai-state>span.active{background:#2ab16c}
.staff-section{margin:0 0 30px}
.staff-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px}
.staff-item{display:grid;gap:7px;padding:13px 15px;background:var(--app-surface);border:1px solid var(--app-border);border-radius:8px}
.staff-item-top{display:flex;align-items:center;justify-content:space-between;gap:8px}
.staff-item-top b{font-size:12px;color:var(--app-text)}
.staff-item>span,.staff-item small{font-size:11px;color:var(--app-muted)}
.board-filters{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:14px}
.kanban-board{display:grid;grid-template-columns:repeat(5,minmax(250px,1fr));gap:12px;overflow-x:auto;padding-bottom:8px;align-items:start}
.kanban-lane{min-width:250px;padding:10px;background:var(--app-lane);border-radius:8px}
.kanban-lane>header{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:2px 2px 10px}
.kanban-lane h3{margin:0;color:var(--app-text);font-size:12px;font-weight:750}
.kanban-orders{display:grid;gap:10px}
.kanban-empty{padding:18px 10px;text-align:center;color:var(--app-muted);font-size:12px;border:1px dashed var(--app-border);border-radius:7px;background:var(--app-soft)}
.mobile-lane-select{display:none;margin-bottom:14px}
@media(max-width:1200px){.metrics-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:1023px){.mobile-lane-select{display:block}.kanban-board{display:block;overflow:visible}.kanban-lane{min-width:0}.board-filters{grid-template-columns:repeat(2,minmax(0,1fr))}.staff-grid{max-height:240px;overflow:auto}.page-heading{align-items:flex-start;flex-wrap:wrap}}
@media(max-width:599px){h1{font-size:28px}.primary-action{font-size:14px;padding:0 14px}.metrics-grid{gap:9px}.section-heading{align-items:flex-start}.ai-state{max-width:155px}}
</style>
