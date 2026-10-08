<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { date } from 'quasar'
import { api, type WorkOrder, type WorkOrderPhoto, type WorkOrderReport } from '../api'

const props = defineProps<{ modelValue: boolean; order: WorkOrder | null; canAnalyze?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()
const report = ref<WorkOrderReport | null>(null)
const photoUrls = ref<Record<number, string>>({})
const photoErrors = ref<Record<number, string>>({})
const retryReport = ref(0)
let retryPhoto: (photoId: number) => Promise<void> = async () => {}
const loading = ref(false)
const error = ref('')
const selectedCompletionId = ref<number | null>(null)
const visionPending = ref(false)
const visionError = ref('')
const visual = computed(() => selectedCompletion.value?.vision)
const selectedCompletion = computed(() => report.value?.completions?.find(item => item.id === selectedCompletionId.value) ?? report.value?.completion ?? null)
const latestSelected = computed(() => selectedCompletion.value?.id === report.value?.completion?.id)
const completionOptions = computed(() => (report.value?.completions ?? []).map((item, index) => ({ value: item.id, label: `Отчёт ${index + 1} · ${date.formatDate(item.created_at, 'DD.MM.YYYY HH:mm')}${item.id === report.value?.completion?.id ? ' · последний' : ''}` })))
const statusLabels: Record<string, string> = {
  issued:'Выдан', accepted:'Принят', queued:'В очереди', rejected:'Отклонён', in_progress:'В работе',
  paused:'Приостановлен', completed:'Исполнен', ai_review:'Проверка ИИ', rework:'На доработке', closed:'Закрыт',
}
const verdictLabels: Record<string, string> = { accepted:'Принят', accepted_with_comments:'Принят с замечаниями', rework:'Требует доработки' }
const photosByType = computed(() => ({
  before: report.value?.photos.filter(photo => photo.photo_type === 'before') ?? [],
  after: report.value?.photos.filter(photo => photo.photo_type === 'after' && (photo.completion_id == null || photo.completion_id === selectedCompletion.value?.id)) ?? [],
}))

watch(() => [props.modelValue, props.order?.id, retryReport.value] as const, async ([isOpen, orderId], _, onCleanup) => {
  let cancelled = false
  const urls: string[] = []
  onCleanup(() => {
    cancelled = true
    urls.forEach(url => URL.revokeObjectURL(url))
  })
  report.value = null
  photoUrls.value = {}
  photoErrors.value = {}
  error.value = ''
  visionError.value = ''
  loading.value = false
  retryPhoto = async () => {}
  if (!isOpen || !orderId) return

  const pendingPhotos = new Set<number>()
  retryPhoto = async photoId => {
    if (cancelled || pendingPhotos.has(photoId)) return
    pendingPhotos.add(photoId)
    delete photoErrors.value[photoId]
    try {
      const blob = await api.workOrderPhoto(orderId, photoId)
      if (cancelled) return
      const url = URL.createObjectURL(blob)
      urls.push(url)
      photoUrls.value = { ...photoUrls.value, [photoId]: url }
    } catch (cause) {
      if (!cancelled) photoErrors.value = { ...photoErrors.value, [photoId]: cause instanceof Error ? cause.message : 'Не удалось загрузить фото' }
    } finally { pendingPhotos.delete(photoId) }
  }
  loading.value = true
  try {
    const data = await api.workOrderReport(orderId)
    if (cancelled) return
    report.value = data
    selectedCompletionId.value = data.completion?.id ?? null
    loading.value = false
    await Promise.all(data.photos.map(photo => retryPhoto(photo.id)))
  } catch (cause) {
    if (!cancelled) error.value = cause instanceof Error ? cause.message : 'Не удалось загрузить отчёт'
  } finally {
    if (!cancelled) loading.value = false
  }
})

function photoCaption(photo: WorkOrderPhoto) {
  return `${photo.original_name || 'Фотография'} · ${date.formatDate(photo.created_at, 'DD.MM.YYYY HH:mm')}`
}

async function analyzePhotos() {
  const orderId = props.order?.id
  const completion = selectedCompletion.value
  if (!orderId || !completion || visionPending.value) return
  visionPending.value = true
  visionError.value = ''
  try {
    const result = await api.analyzePhotos(orderId, completion.id)
    if (props.order?.id === orderId && report.value) {
      const item = report.value.completions?.find(item => item.id === completion.id) ?? report.value.completion
      if (item) item.vision = result
    }
  } catch (cause) {
    if (props.order?.id === orderId) visionError.value = cause instanceof Error ? cause.message : 'Не удалось запустить анализ'
  } finally { visionPending.value = false }
}
</script>

<template>
  <q-dialog :model-value="modelValue" @update:model-value="emit('update:modelValue', $event)">
    <q-card class="report-dialog">
      <q-card-section class="report-heading">
        <div><div class="eyebrow">Отчёт по наряду</div><h2>{{ order?.number }}</h2></div>
        <q-btn flat round icon="close" aria-label="Закрыть" @click="emit('update:modelValue', false)" />
      </q-card-section>
      <q-card-section v-if="loading" class="report-state"><q-spinner color="primary" size="30px" /></q-card-section>
      <q-card-section v-else-if="error" class="report-state text-negative">{{ error }}<div><q-btn flat no-caps label="Повторить" @click="retryReport++" /></div></q-card-section>
      <div v-else-if="report" class="report-content">
        <section class="report-summary">
          <div class="summary-main"><q-badge color="primary">{{ statusLabels[report.order.status] }}</q-badge><p>{{ report.order.description }}</p></div>
          <dl>
            <div><dt>Оборудование</dt><dd>{{ report.order.equipment_name || 'Не указано' }}<small v-if="report.order.inventory_number">{{ report.order.inventory_number }}</small></dd></div>
            <div><dt>Участок</dt><dd>{{ report.order.site_name || 'Не указан' }}</dd></div>
            <div><dt>Исполнитель</dt><dd>{{ report.order.assignee_name || 'Не назначен' }}</dd></div>
            <div><dt>Мастер</dt><dd>{{ report.order.master_name || 'Не указан' }}</dd></div>
            <div><dt>Выдан</dt><dd>{{ date.formatDate(report.order.created_at, 'DD.MM.YYYY HH:mm') }}</dd></div>
            <div><dt>Срок</dt><dd>{{ date.formatDate(report.order.due_at, 'DD.MM.YYYY HH:mm') }}</dd></div>
          </dl>
        </section>

        <section v-if="selectedCompletion" class="report-section">
          <q-select v-if="completionOptions.length > 1" v-model="selectedCompletionId" outlined dense emit-value map-options label="Версия отчёта" :options="completionOptions" class="q-mb-md" />
          <h3>Выполненные работы</h3>
          <p class="work-text">{{ selectedCompletion.work_performed }}</p>
          <p v-if="selectedCompletion.comment" class="muted-note">{{ selectedCompletion.comment }}</p>
          <p v-if="selectedCompletion.fault_code" class="fault-code"><b>{{ selectedCompletion.fault_code.code }}</b> · {{ selectedCompletion.fault_code.name }}</p>
          <div v-if="selectedCompletion.materials.length" class="materials-table">
            <div v-for="material in selectedCompletion.materials" :key="material.name"><span>{{ material.name }}</span><b>{{ material.quantity }} {{ material.unit }}</b></div>
          </div>
        </section>

        <section v-if="report.inspection && latestSelected" class="report-section inspection-result">
          <div class="inspection-heading"><h3>Проверка выполнения</h3><strong>{{ report.inspection.score }}/100</strong></div>
          <div class="inspection-meta">{{ verdictLabels[report.inspection.verdict] }} · {{ report.inspection.analysis_source === 'local_llm' ? report.inspection.model_name : 'Правила' }} · уверенность {{ Math.round(report.inspection.confidence * 100) }}%</div>
          <p>{{ report.inspection.explanation }}</p>
          <ul><li v-for="check in report.inspection.checks" :key="check.code" :class="{ failed: !check.passed }"><q-icon :name="check.passed ? 'check_circle' : 'error_outline'" /> <b>{{ check.label }}:</b> {{ check.detail }}</li></ul>
        </section>

        <section v-if="selectedCompletion" class="report-section">
          <h3>Визуальные наблюдения · экспериментальная VLM</h3>
          <p class="muted-note">Подсказка, не заключение об исправности или качестве ремонта. Приёмку выполняет мастер.</p>
          <p v-if="visual" class="muted-note">{{ visual.model_name }} · {{ visual.status === 'done' ? 'Готово' : visual.status === 'running' ? 'Анализ выполняется' : 'Ошибка анализа' }}</p>
          <template v-if="visual?.result">
            <ul><li v-for="item in visual.result.observations" :key="item">{{ item }}</li></ul>
            <p v-if="!visual.result.observations.length" class="muted-note">Модель не сформулировала наблюдений.</p>
            <p v-for="item in visual.result.limitations" :key="item" class="muted-note">{{ item }}</p>
            <p class="muted-note">Нужна проверка человеком. Использованы фото: {{ visual.photo_ids.join(', ') }}.</p>
          </template>
          <p v-if="visual?.error || visionError" class="text-negative">{{ visionError || visual?.error }}</p>
          <p v-if="!report.vision_enabled && !visual?.result" class="muted-note">VLM отключена. Работа с нарядом доступна без анализа фото.</p>
          <q-btn v-if="canAnalyze && latestSelected && report.vision_enabled && visual?.status !== 'done'" outline no-caps color="primary" :label="visual?.status === 'running' ? 'Проверить статус / повторить' : visual?.status === 'failed' ? 'Повторить анализ фото' : 'Проанализировать фото'" :loading="visionPending" :disable="!photosByType.after.length || !['completed','ai_review','closed'].includes(report.order.status)" @click="analyzePhotos" />
        </section>

        <section v-if="report.photos.length" class="report-section">
          <h3>Фото до и после</h3>
          <div class="photos-compare">
            <div v-for="group in [{type:'before',label:'До ремонта',photos:photosByType.before},{type:'after',label:'После ремонта',photos:photosByType.after}]" :key="group.type" class="photo-group">
              <h4>{{ group.label }}</h4>
              <figure v-for="photo in group.photos" :key="photo.id">
                <q-img v-if="photoUrls[photo.id]" :src="photoUrls[photo.id]" :alt="photo.original_name || 'Фото по наряду'" loading="lazy" fit="contain" :ratio="4/3"><template #error><div class="absolute-full flex flex-center text-negative bg-red-1">Файл изображения повреждён</div></template></q-img>
                <div v-else-if="photoErrors[photo.id]" class="image-pending text-negative"><span>{{ photoErrors[photo.id] }}</span><q-btn flat no-caps label="Повторить" @click="retryPhoto(photo.id)" /></div>
                <div v-else class="image-pending"><q-spinner size="22px" /></div>
                <figcaption>{{ photoCaption(photo) }}</figcaption>
              </figure>
              <p v-if="!group.photos.length" class="muted-note">Фото не приложено</p>
            </div>
          </div>
        </section>

        <section class="report-section">
          <h3>Хронология</h3>
          <ol class="timeline">
            <li v-for="(event, index) in report.events" :key="`${event.created_at}-${index}`">
              <span class="timeline-dot" />
              <div><b>{{ event.from_status ? `${statusLabels[event.from_status]} → ` : '' }}{{ statusLabels[event.to_status] }}</b><time>{{ date.formatDate(event.created_at, 'DD.MM.YYYY HH:mm:ss') }}</time><p>{{ event.actor_name }}<template v-if="event.comment"> · {{ event.comment }}</template></p></div>
            </li>
          </ol>
        </section>
      </div>
    </q-card>
  </q-dialog>
</template>

<style scoped>
.report-dialog{width:min(900px,96vw);max-width:900px;max-height:90vh;border-radius:10px}.report-heading{position:sticky;top:0;z-index:1;display:flex;align-items:center;justify-content:space-between;padding:18px 24px;background:var(--app-surface);border-bottom:1px solid var(--app-border)}.report-heading h2{margin:4px 0 0;font-size:22px;color:var(--app-text)}.eyebrow{text-transform:uppercase;font-size:10px;font-weight:800;color:var(--app-accent)}.report-content{max-height:calc(90vh - 76px);overflow:auto}.report-summary,.report-section{padding:20px 24px;border-bottom:1px solid var(--app-lane)}.summary-main{display:flex;align-items:center;gap:12px}.summary-main p{margin:0;color:var(--app-text);font-size:14px;font-weight:600}.report-summary dl{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin:18px 0 0}.report-summary dt{font-size:10px;color:var(--app-muted)}.report-summary dd{margin:4px 0 0;color:var(--app-text);font-size:12px;font-weight:650}.report-summary dd small{display:block;margin-top:2px;color:var(--app-muted);font-weight:400}.report-section h3{margin:0 0 12px;font-size:14px;color:var(--app-text)}.work-text,.inspection-result>p{margin:0;color:var(--app-text);font-size:13px;line-height:1.55;white-space:pre-wrap}.muted-note{color:var(--app-muted);font-size:11px;line-height:1.5}.fault-code{margin:12px 0 0;color:var(--app-muted);font-size:12px}.materials-table{margin-top:14px;border-top:1px solid var(--app-border)}.materials-table>div{display:flex;justify-content:space-between;gap:16px;padding:8px 2px;border-bottom:1px solid var(--app-border);font-size:11px;color:var(--app-muted)}.materials-table b{white-space:nowrap}.inspection-result{background:var(--app-soft)}.inspection-heading{display:flex;justify-content:space-between;align-items:center}.inspection-heading h3{margin-bottom:5px}.inspection-heading strong{font-size:19px;color:var(--app-accent)}.inspection-meta{margin-bottom:10px;color:var(--app-muted);font-size:10px}.inspection-result ul{display:grid;gap:7px;padding:0;margin:12px 0 0;list-style:none}.inspection-result li{display:flex;align-items:flex-start;gap:5px;color:var(--app-muted);font-size:11px;line-height:1.45}.inspection-result li .q-icon{color:var(--app-accent)}.inspection-result li.failed,.inspection-result li.failed .q-icon{color:var(--app-red-text)}.photos-compare{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.photo-group h4{margin:0 0 8px;font-size:12px;color:var(--app-muted)}.photo-group figure{margin:0 0 10px;overflow:hidden;border:1px solid var(--app-border);border-radius:8px;background:var(--app-soft)}.photo-group figcaption{padding:8px;font-size:10px;color:var(--app-muted);overflow-wrap:anywhere}.image-pending{display:grid;place-items:center;aspect-ratio:4/3}.timeline{position:relative;display:grid;gap:0;margin:0;padding:0 0 0 7px;list-style:none}.timeline:before{position:absolute;top:7px;bottom:8px;left:12px;width:1px;background:var(--app-border);content:""}.timeline li{position:relative;display:grid;grid-template-columns:18px 1fr;gap:10px;padding:0 0 17px}.timeline-dot{z-index:1;width:11px;height:11px;margin-top:3px;border:2px solid var(--app-surface);border-radius:50%;background:#3e8a61;box-shadow:0 0 0 1px var(--app-border)}.timeline li>div{display:grid;grid-template-columns:1fr auto;gap:4px 12px}.timeline b{font-size:11px;color:var(--app-text)}.timeline time{font-size:10px;color:var(--app-muted)}.timeline p{grid-column:1/-1;margin:0;color:var(--app-muted);font-size:10px;line-height:1.4}.report-state{padding:40px;text-align:center}@media(max-width:640px){.report-summary,.report-section{padding:16px}.report-summary dl{grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.photos-compare{grid-template-columns:1fr}.summary-main{align-items:flex-start;flex-direction:column}.report-dialog{max-height:94vh}.report-content{max-height:calc(94vh - 76px)}}
.report-dialog{display:flex;flex-direction:column;overflow:hidden}.report-heading{flex-shrink:0}.report-content{min-height:0}
</style>
