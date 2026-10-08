<script setup lang="ts">
import { date } from 'quasar'
import type { AiInspection, WorkOrder } from '../api'

defineProps<{ order: WorkOrder; equipment: string; assignee?: string; statusLabel: string; statusColor: string; overdue: boolean; review?: AiInspection; compact?: boolean }>()
</script>

<template>
  <article :class="['order-card', { overdue, compact, emergency: order.priority === 'emergency' }]">
    <div class="order-top">
      <div><div class="order-number">{{ order.number }}</div><div class="equipment">{{ equipment }}</div></div>
      <q-badge rounded :color="statusColor" class="status-badge">{{ statusLabel }}</q-badge>
    </div>
    <p class="description">{{ order.description }}</p>
    <div class="order-meta">
      <div v-if="assignee"><q-icon name="person_outline" />{{ assignee }}</div>
      <div :class="{ 'deadline-overdue': overdue }"><q-icon name="schedule" />до {{ date.formatDate(order.due_at, 'DD.MM, HH:mm') }}</div>
    </div>
    <div v-if="review" class="ai-result">
      <div class="ai-heading"><span><q-icon name="psychology" /> AI-проверка</span><b>{{ review.score }}/100</b></div>
      <p>{{ review.explanation }}</p>
      <div class="ai-meta">{{ review.analysis_source === 'local_llm' ? review.model_name : 'Резервные правила' }} · уверенность {{ Math.round(review.confidence * 100) }}%</div>
    </div>
    <div v-if="$slots.actions" class="card-actions"><slot name="actions" /></div>
  </article>
</template>

<style scoped>
.order-card{position:relative;display:flex;flex-direction:column;min-height:278px;padding:20px;background:var(--app-surface);border:1px solid var(--app-border);border-radius:16px;box-shadow:0 3px 12px rgb(20 52 40/4%);transition:.18s ease}.order-card:before{content:"";position:absolute;left:-1px;top:22px;bottom:22px;width:3px;border-radius:0 4px 4px 0;background:#4f8c70;opacity:.55}.order-card:hover{transform:translateY(-2px);border-color:var(--app-border);box-shadow:0 12px 26px rgb(20 52 40/8%)}.order-card.overdue:before,.order-card.emergency:before{background:#d0473d;opacity:1}.order-card.compact{min-height:0}.order-top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}.order-number{font-weight:800;font-size:17px;letter-spacing:.01em}.equipment{color:var(--app-muted);font-size:12px;margin-top:4px}.status-badge{padding:6px 9px;font-size:10px;font-weight:700}.description{font-size:14px;line-height:1.55;margin:18px 0;color:var(--app-text);flex:1}.order-meta{display:flex;justify-content:space-between;flex-wrap:wrap;gap:9px;padding-top:14px;border-top:1px solid var(--app-border);color:var(--app-muted);font-size:11px}.order-meta div{display:flex;align-items:center;gap:5px}.deadline-overdue{color:var(--app-red-text)!important;font-weight:700}.ai-result{margin-top:15px;padding:13px;border-radius:11px;background:var(--app-purple-bg);color:var(--app-purple-text)}.ai-heading{display:flex;align-items:center;justify-content:space-between;font-size:12px}.ai-heading span{font-weight:700}.ai-heading .q-icon{font-size:18px;margin-right:5px}.ai-heading b{font-size:14px}.ai-result p{font-size:11px;line-height:1.45;margin:7px 0}.ai-meta{font-size:9px;opacity:.72}.card-actions{display:flex;gap:8px;margin-top:16px}.card-actions :deep(.q-btn){border-radius:10px;min-height:40px;font-weight:700}
</style>
<style scoped>
.card-actions{flex-wrap:wrap}.card-actions :deep(.q-btn){min-width:0}
.order-top>div{min-width:0}.equipment,.description,.ai-result p,.ai-meta{overflow-wrap:anywhere}
.status-badge{flex-shrink:0;max-width:50%;white-space:normal;text-align:center}
.order-meta .q-icon{flex:0 0 auto;font-size:16px}
.ai-heading span{display:flex;align-items:center;gap:5px}.ai-heading .q-icon{margin-right:0;flex-shrink:0}
@media(max-width:599px){.card-actions :deep(.q-btn){flex:1 1 45%;min-height:48px}}
</style>
