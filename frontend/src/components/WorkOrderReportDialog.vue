<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { date } from 'quasar'
import { api, type WorkOrder, type WorkOrderPhoto, type WorkOrderReport } from '../api'

const props = defineProps<{ modelValue: boolean; order: WorkOrder | null }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()
const report = ref<WorkOrderReport | null>(null)
const photoUrls = ref<Record<number, string>>({})
const loading = ref(false)
const error = ref('')
const statusLabels: Record<string, string> = {
  issued:'Выдан', accepted:'Принят', queued:'В очереди', rejected:'Отклонён', in_progress:'В работе',
  paused:'Приостановлен', completed:'Исполнен', ai_review:'Проверка ИИ', rework:'На доработке', closed:'Закрыт',
}
const verdictLabels: Record<string, string> = { accepted:'Принят', accepted_with_comments:'Принят с замечаниями', rework:'Требует доработки' }
const photosByType = computed(() => ({
  before: report.value?.photos.filter(photo => photo.photo_type === 'before') ?? [],
  after: report.value?.photos.filter(photo => photo.photo_type === 'after') ?? [],
}))

watch(() => [props.modelValue, props.order?.id] as const, async ([isOpen, orderId], _, onCleanup) => {
  let cancelled = false
  const urls: string[] = []
  onCleanup(() => {
    cancelled = true
    urls.forEach(url => URL.revokeObjectURL(url))
  })
  report.value = null
  photoUrls.value = {}
  error.value = ''
  if (!isOpen || !orderId) return

  loading.value = true
  try {
    const data = await api.workOrderReport(orderId)
    if (cancelled) return
    report.value = data
    for (const photo of data.photos) {
      const url = URL.createObjectURL(await api.workOrderPhoto(orderId, photo.id))
      if (cancelled) {
        URL.revokeObjectURL(url)
        return
      }
      urls.push(url)
      photoUrls.value = { ...photoUrls.value, [photo.id]: url }
    }
  } catch (cause) {
    if (!cancelled) error.value = cause instanceof Error ? cause.message : 'Не удалось загрузить отчёт'
  } finally {
    if (!cancelled) loading.value = false
  }
})

function photoCaption(photo: WorkOrderPhoto) {
  return `${photo.original_name || 'Фотография'} · ${date.formatDate(photo.created_at, 'DD.MM.YYYY HH:mm')}`
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
      <q-card-section v-else-if="error" class="report-state text-negative">{{ error }}</q-card-section>
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

        <section v-if="report.completion" class="report-section">
          <h3>Выполненные работы</h3>
          <p class="work-text">{{ report.completion.work_performed }}</p>
          <p v-if="report.completion.comment" class="muted-note">{{ report.completion.comment }}</p>
          <p v-if="report.completion.fault_code" class="fault-code"><b>{{ report.completion.fault_code.code }}</b> · {{ report.completion.fault_code.name }}</p>
          <div v-if="report.completion.materials.length" class="materials-table">
            <div v-for="material in report.completion.materials" :key="material.name"><span>{{ material.name }}</span><b>{{ material.quantity }} {{ material.unit }}</b></div>
          </div>
        </section>

        <section v-if="report.inspection" class="report-section inspection-result">
          <div class="inspection-heading"><h3>Проверка выполнения</h3><strong>{{ report.inspection.score }}/100</strong></div>
          <div class="inspection-meta">{{ verdictLabels[report.inspection.verdict] }} · {{ report.inspection.analysis_source === 'local_llm' ? report.inspection.model_name : 'Правила' }} · уверенность {{ Math.round(report.inspection.confidence * 100) }}%</div>
          <p>{{ report.inspection.explanation }}</p>
          <ul><li v-for="check in report.inspection.checks" :key="check.code" :class="{ failed: !check.passed }"><q-icon :name="check.passed ? 'check_circle' : 'error_outline'" /> <b>{{ check.label }}:</b> {{ check.detail }}</li></ul>
        </section>

        <section v-if="report.photos.length" class="report-section">
          <h3>Фото до и после</h3>
          <div class="photos-compare">
            <div v-for="group in [{type:'before',label:'До ремонта',photos:photosByType.before},{type:'after',label:'После ремонта',photos:photosByType.after}]" :key="group.type" class="photo-group">
              <h4>{{ group.label }}</h4>
              <figure v-for="photo in group.photos" :key="photo.id">
                <q-img v-if="photoUrls[photo.id]" :src="photoUrls[photo.id]" fit="contain" :ratio="4/3" />
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
.report-dialog{width:min(900px,96vw);max-width:900px;max-height:90vh;border-radius:10px}.report-heading{position:sticky;top:0;z-index:1;display:flex;align-items:center;justify-content:space-between;padding:18px 24px;background:#fff;border-bottom:1px solid #e4ebe6}.report-heading h2{margin:4px 0 0;font-size:22px;color:#1e3027}.eyebrow{text-transform:uppercase;font-size:10px;font-weight:800;color:#438064}.report-content{max-height:calc(90vh - 76px);overflow:auto}.report-summary,.report-section{padding:20px 24px;border-bottom:1px solid #e9eeeb}.summary-main{display:flex;align-items:center;gap:12px}.summary-main p{margin:0;color:#26372e;font-size:14px;font-weight:600}.report-summary dl{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin:18px 0 0}.report-summary dt{font-size:10px;color:#839087}.report-summary dd{margin:4px 0 0;color:#28372f;font-size:12px;font-weight:650}.report-summary dd small{display:block;margin-top:2px;color:#78857d;font-weight:400}.report-section h3{margin:0 0 12px;font-size:14px;color:#26382e}.work-text,.inspection-result>p{margin:0;color:#33433a;font-size:13px;line-height:1.55;white-space:pre-wrap}.muted-note{color:#7a877f;font-size:11px;line-height:1.5}.fault-code{margin:12px 0 0;color:#496454;font-size:12px}.materials-table{margin-top:14px;border-top:1px solid #e8ede9}.materials-table>div{display:flex;justify-content:space-between;gap:16px;padding:8px 2px;border-bottom:1px solid #eef1ef;font-size:11px;color:#46564c}.materials-table b{white-space:nowrap}.inspection-result{background:#f8faf8}.inspection-heading{display:flex;justify-content:space-between;align-items:center}.inspection-heading h3{margin-bottom:5px}.inspection-heading strong{font-size:19px;color:#246b48}.inspection-meta{margin-bottom:10px;color:#738178;font-size:10px}.inspection-result ul{display:grid;gap:7px;padding:0;margin:12px 0 0;list-style:none}.inspection-result li{display:flex;align-items:flex-start;gap:5px;color:#4b5b51;font-size:11px;line-height:1.45}.inspection-result li .q-icon{color:#33855b}.inspection-result li.failed,.inspection-result li.failed .q-icon{color:#b74b3f}.photos-compare{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.photo-group h4{margin:0 0 8px;font-size:12px;color:#53645a}.photo-group figure{margin:0 0 10px;overflow:hidden;border:1px solid #e0e8e2;border-radius:8px;background:#f6f8f6}.photo-group figcaption{padding:8px;font-size:10px;color:#6e7d73;overflow-wrap:anywhere}.image-pending{display:grid;place-items:center;aspect-ratio:4/3}.timeline{position:relative;display:grid;gap:0;margin:0;padding:0 0 0 7px;list-style:none}.timeline:before{position:absolute;top:7px;bottom:8px;left:12px;width:1px;background:#d7e2da;content:""}.timeline li{position:relative;display:grid;grid-template-columns:18px 1fr;gap:10px;padding:0 0 17px}.timeline-dot{z-index:1;width:11px;height:11px;margin-top:3px;border:2px solid #fff;border-radius:50%;background:#3e8a61;box-shadow:0 0 0 1px #a9c5b2}.timeline li>div{display:grid;grid-template-columns:1fr auto;gap:4px 12px}.timeline b{font-size:11px;color:#314238}.timeline time{font-size:10px;color:#87928b}.timeline p{grid-column:1/-1;margin:0;color:#68766d;font-size:10px;line-height:1.4}.report-state{padding:40px;text-align:center}@media(max-width:640px){.report-summary,.report-section{padding:16px}.report-summary dl{grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.photos-compare{grid-template-columns:1fr}.summary-main{align-items:flex-start;flex-direction:column}.report-dialog{max-height:94vh}.report-content{max-height:calc(94vh - 76px)}}
</style>