<script setup lang="ts">
import type { WorkOrder, WorkOrderStatus, Directories, AiInspection } from '../api'
import { statusMeta, name, isOverdue, actions } from '../utils/workOrders'
import OrderCard from './OrderCard.vue'
import DashboardState from './DashboardState.vue'
defineProps<{ orders: WorkOrder[]; directories?: Directories; reviews: AiInspection[]; loading: boolean; error?: string; offline: boolean; pending: boolean }>()
const emit = defineEmits<{ action: [order: WorkOrder, status: WorkOrderStatus]; report: [order: WorkOrder]; retry: [] }>()
</script>
<template><div>
        <div class="page-heading worker-heading"><div><div class="eyebrow">Рабочее место исполнителя</div><h1>Мои наряды</h1><p>{{ orders.length }} активных задач на смену</p></div></div>
        <DashboardState :loading="loading" :error="error" :offline="offline" :has-data="orders.length > 0" @retry="emit('retry')" />
        <div class="worker-list"><OrderCard v-for="order in orders" :key="order.id" compact :order="order" :equipment="name(directories?.equipment,order.equipment_id)" :status-label="statusMeta[order.status].label" :status-color="statusMeta[order.status].color" :overdue="isOverdue(order)" :review="reviews.find(review => review.work_order_id === order.id)"><template #actions><q-btn flat no-caps icon="description" label="Отчёт и фото" @click="emit('report', order)"/><q-btn v-for="action in actions(order)" :key="action.status" unelevated no-caps size="lg" class="col" :color="action.color" :icon="action.icon" :label="action.label" :loading="pending" @click="emit('action', order, action.status)"/></template></OrderCard></div>
        <div v-if="!loading && !error && !orders.length" class="empty-state"><q-icon name="task_alt"/><h3>Нет активных нарядов</h3><p>Новые наряды появятся здесь автоматически.</p></div>

</div></template>
<style scoped>
.eyebrow{text-transform:uppercase;letter-spacing:.14em;color:var(--app-accent);font-size:10px;font-weight:800}
.page-heading{margin-bottom:28px}
h1{font-size:34px;line-height:1.1;letter-spacing:-.035em;margin:7px 0 5px;color:var(--app-text)}
.page-heading p{margin:0;color:var(--app-muted);font-size:13px}
.worker-list{display:grid;gap:14px;max-width:780px}
.empty-state{display:grid;place-items:center;text-align:center;min-height:320px;padding:36px;border:1px dashed var(--app-border);border-radius:18px;background:var(--app-soft);color:var(--app-muted)}
.empty-state .q-icon{font-size:54px;color:var(--app-accent)}
.empty-state h3{margin:14px 0 3px;color:var(--app-text)}
.empty-state p{margin:0;font-size:13px}
@media(max-width:599px){h1{font-size:28px}}
</style>
