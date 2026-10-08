<script setup lang="ts">
import { computed, ref } from 'vue'
import type { QueuedAction } from '../offline'
import { statusMeta } from '../utils/workOrders'
const props = defineProps<{ actions: QueuedAction[]; syncing: boolean; online: boolean }>()
const emit = defineEmits<{ sync: []; retry: [id: number] }>()
const expanded = ref(false)
const conflicts = computed(() => props.actions.filter(action => action.state === 'conflict').length)
function completionText(action: QueuedAction) {
  return action.kind === 'completion' ? action.payload.entries.filter(([key, value]) => ['work_performed', 'comment'].includes(key) && typeof value === 'string').map(([, value]) => value).join('\n') : action.payload.comment
}
function photoCount(action: QueuedAction) {
  return action.kind === 'completion' ? action.payload.entries.filter(([, value]) => typeof value !== 'string').length : 0
}
</script>
<template>
  <q-card v-if="actions.length" flat bordered class="queue-panel q-mb-md">
    <q-card-section class="row items-center q-gutter-sm">
      <q-icon :name="conflicts ? 'warning_amber' : 'cloud_upload'" :color="conflicts ? 'negative' : 'primary'" size="24px" />
      <div class="col"><b>На устройстве: {{ actions.length }} действий</b><div class="text-caption">{{ conflicts ? `Требуют разбора: ${conflicts}. Данные и фото сохранены.` : 'Ожидают подтверждения сервера' }}</div></div>
      <q-btn flat no-caps label="Подробнее" :aria-expanded="expanded" @click="expanded = !expanded" />
      <q-btn outline no-caps label="Отправить" :loading="syncing" :disable="!online" @click="emit('sync')" />
    </q-card-section>
    <q-card-section v-if="expanded" class="queue-items">
      <article v-for="action in actions" :key="action.id">
        <b>Наряд #{{ action.payload.orderId }} · {{ action.kind === 'completion' ? 'Отчёт о выполнении' : statusMeta[action.payload.status].label }}</b>
        <p v-if="completionText(action)" class="saved-text">{{ completionText(action) }}</p>
        <span v-if="photoCount(action)" class="text-caption">Сохранено фото: {{ photoCount(action) }}</span>
        <p v-if="action.error" class="text-negative">{{ action.error }}</p>
        <div v-if="action.state === 'conflict'" class="text-caption">Проверьте статус наряда перед повторной отправкой. Последующие действия этого наряда приостановлены.</div>
        <q-btn v-if="action.state === 'conflict'" flat no-caps color="primary" label="Повторить после проверки" :disable="!online || syncing" @click="emit('retry', action.id!)" />
      </article>
    </q-card-section>
  </q-card>
</template>
<style scoped>
.queue-panel{border-radius:12px;background:var(--app-amber-bg)}.queue-items{display:grid;gap:12px}.queue-items article{padding:12px;border:1px solid var(--app-border);border-radius:8px;font-size:13px}.saved-text{white-space:pre-wrap;overflow-wrap:anywhere}.queue-items p{margin:6px 0}
</style>
