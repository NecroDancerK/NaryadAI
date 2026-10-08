<script setup lang="ts">
import { onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import type { Directories, WorkOrder } from '../api'
import { completionDraftKey, loadCompletionDraft, saveCompletionDraft, type CompletionDraft } from '../offline'

const props = defineProps<{ modelValue: boolean; userId?: number; order?: WorkOrder; directories?: Directories; loading: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; submit: [input: { id:number; userId:number; data:FormData; draftRevision?:string }] }>()
const form = reactive({ work_performed: '', fault_code_id: 1, material_id: null as number | null, quantity: 1, photo: null as File | null, comment: '' })
const usages = ref<Array<{ material_id: number; quantity: number }>>([])
const $q = useQuasar()

const hydrating = ref(false)
const saving = ref(false)
const submitting = ref(false)
const draftNotice = ref('')
const draftError = ref('')
let session: { userId:number; orderId:number; revision?:string } | undefined
let generation = 0
let writes: Promise<void> = Promise.resolve()

function reset() {
  form.work_performed = ''; form.fault_code_id = props.directories?.fault_codes[0]?.id ?? 1
  form.material_id = null; form.quantity = 1; form.photo = null; form.comment = ''; usages.value = []
}
watch(() => [props.modelValue, props.userId, props.order?.id] as const, async ([open,userId,orderId]) => {
  const ownGeneration = ++generation
  session = undefined
  hydrating.value = true
  draftError.value = ''; draftNotice.value = ''; submitting.value = false
  reset()
  if (!open || !userId || !orderId) { hydrating.value = false; return }
  try {
    await writes
    const draft = await loadCompletionDraft(userId, orderId)
    if (ownGeneration !== generation) return
    if (draft) {
      form.work_performed = draft.work_performed; form.fault_code_id = draft.fault_code_id
      form.material_id = draft.material_id; form.quantity = draft.quantity; form.comment = draft.comment
      form.photo = draft.photo ? new File([draft.photo], draft.photoName ?? draft.photo.name ?? 'photo', {type:draft.photo.type,lastModified:draft.photoModified}) : null
      usages.value = draft.usages
      draftNotice.value = 'Черновик восстановлен с этого устройства'
    }
    session = {userId,orderId,revision:draft?.revision}
  } catch (error) {
    if (ownGeneration === generation) {
      session = {userId,orderId}
      draftError.value = error instanceof Error ? error.message : 'Хранилище недоступно. Черновик не восстановлен.'
    }
  } finally { if (ownGeneration === generation) hydrating.value = false }
}, {immediate:true})

function save() {
  if (!session || hydrating.value || submitting.value || props.loading) return
  const ownSession = session
  const draft: CompletionDraft = {
    ...form, usages:usages.value.map(item => ({...item})),
    key:completionDraftKey(ownSession.userId,ownSession.orderId), userId:ownSession.userId, orderId:ownSession.orderId,
    revision:crypto.randomUUID(),updatedAt:new Date().toISOString(),
    photoName:form.photo?.name,photoModified:form.photo?.lastModified,
  }
  saving.value = true
  const run = writes.then(async () => {
    await saveCompletionDraft(draft,ownSession.revision)
    ownSession.revision = draft.revision
    if (session === ownSession) { draftError.value = ''; draftNotice.value = 'Черновик сохранён на этом устройстве' }
  }).catch(error => {
    if (session === ownSession) draftError.value = error instanceof Error ? error.message : 'Черновик не сохранён'
  })
  writes = run
  void run.then(() => { if (writes === run) saving.value = false })
}
watch([form,usages],save,{deep:true,flush:'sync'})
watch(() => props.loading, loading => { if (!loading) submitting.value = false })

async function close() {
  await writes
  if (draftError.value) {
    const ownSession = session
    $q.dialog({title:'Черновик не сохранён',message:'Закрыть форму и потерять несохранённые поля?',cancel:{label:'Остаться'},ok:{label:'Закрыть без сохранения'},persistent:true}).onOk(() => {
      if (session === ownSession) emit('update:modelValue',false)
    })
    return
  }
  emit('update:modelValue',false)
}
function warnBeforeUnload(event: BeforeUnloadEvent) {
  if (props.modelValue && (saving.value || draftError.value)) { event.preventDefault(); event.returnValue = '' }
}
window.addEventListener('beforeunload',warnBeforeUnload)
onBeforeUnmount(() => { ++generation; window.removeEventListener('beforeunload',warnBeforeUnload) })

function materialName(id: number) { return props.directories?.materials.find(item => item.id === id)?.name ?? `#${id}` }
function addMaterial() {
  if (!form.material_id || form.quantity <= 0) return
  const existing = usages.value.find(item => item.material_id === form.material_id)
  if (existing) existing.quantity += form.quantity
  else usages.value.push({ material_id: form.material_id, quantity: form.quantity })
  form.material_id = null; form.quantity = 1
}
async function submit() {
  if (!session || submitting.value || props.loading || hydrating.value) return
  const ownSession = session
  submitting.value = true
  await writes
  if (session !== ownSession) { submitting.value = false; return }
  const data = new FormData()
  data.append('work_performed', form.work_performed)
  data.append('fault_code_id', String(form.fault_code_id))
  data.append('materials_json', JSON.stringify(usages.value))
  if (form.comment) data.append('comment', form.comment)
  if (form.photo) data.append('photo', form.photo)
  emit('submit', {id:ownSession.orderId,userId:ownSession.userId,data,draftRevision:ownSession.revision})
}
</script>

<template>
  <q-dialog :model-value="modelValue" persistent @update:model-value="emit('update:modelValue', $event)">
    <q-card class="work-dialog">
      <q-card-section class="dialog-heading"><div><div class="dialog-eyebrow">Результат работ</div><div class="text-h5 text-weight-bold">Отчёт {{ order?.number }}</div><div class="text-caption text-grey-7">Зафиксируйте фактически выполненные работы</div></div><q-btn flat round icon="close" :disable="loading || submitting || hydrating" @click="close"/></q-card-section>
      <q-form @submit.prevent="submit">
        <q-card-section class="dialog-body q-gutter-md">
          <q-banner v-if="draftError" class="bg-red-1 text-negative" role="alert">{{ draftError }} Отчёт можно сдать в очередь; не закрывайте форму до подтверждения сохранения.<template #action><q-btn flat label="Повторить сохранение" :disable="saving || loading || submitting" @click="save"/></template></q-banner>
          <div v-else class="text-caption" role="status">{{ hydrating ? 'Восстанавливаем черновик…' : saving ? 'Сохраняем черновик…' : draftNotice || 'Черновик сохраняется при изменении полей' }}</div>
          <fieldset :disabled="hydrating || loading || submitting" :inert="hydrating || loading || submitting" class="completion-fields q-gutter-md">
          <q-input v-model="form.work_performed" outlined autogrow label="Выполненные работы *" :rules="[value => value.length >= 5 || 'Опишите выполненные работы']"/>
          <q-select v-model="form.fault_code_id" outlined emit-value map-options label="Шифр неисправности *" :options="directories?.fault_codes" option-value="id" :option-label="item => `${item.code} — ${item.name}`"/>
          <div class="field-label">Списанные материалы</div><div class="row q-col-gutter-sm"><q-select v-model="form.material_id" class="col" outlined dense emit-value map-options clearable label="Материал" :options="directories?.materials" option-value="id" :option-label="item => `${item.name}, ${item.unit}`"/><q-input v-model.number="form.quantity" class="col-3" outlined dense type="number" min="0.001" step="0.001" label="Кол-во"/><div class="col-auto"><q-btn round unelevated color="primary" icon="add" @click="addMaterial"/></div></div>
          <q-list v-if="usages.length" bordered separator class="rounded-borders"><q-item v-for="(usage,index) in usages" :key="usage.material_id"><q-item-section>{{ materialName(usage.material_id) }}</q-item-section><q-item-section side>{{ usage.quantity }}</q-item-section><q-item-section side><q-btn flat round dense icon="delete_outline" color="negative" @click="usages.splice(index,1)"/></q-item-section></q-item></q-list>
          <q-file v-model="form.photo" outlined accept="image/jpeg,image/png,image/webp" capture="environment" :label="order?.work_type==='unplanned'?'Фото после ремонта *':'Фото после ремонта'" max-file-size="10485760" hint="JPEG, PNG, WebP; до 10 МиБ и 24 Мп, сторона до 8192 px" @rejected="$q.notify({type:'warning',message:'Фото не выбрано: нужен JPEG, PNG или WebP до 10 МиБ. HEIC нужно преобразовать'})"><template #prepend><q-icon name="photo_camera"/></template></q-file>
          <q-input v-model="form.comment" outlined autogrow label="Комментарий"/>
          <div class="ai-note"><q-icon name="fact_check"/><div><b>Далее — проверка мастером</b><span>AI-анализ, если включён и запущен мастером, даёт только рекомендации. Решение о приёмке принимает человек.</span></div></div>
          </fieldset>
        </q-card-section>
        <q-card-actions align="right" class="dialog-actions"><q-btn flat no-caps label="Закрыть" :disable="loading || submitting || hydrating" @click="close"/><q-btn unelevated no-caps color="positive" type="submit" icon="task_alt" label="Сдать отчёт" :disable="hydrating" :loading="loading || submitting"/></q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<style scoped>
.completion-fields{border:0;padding:0;margin:0;min-width:0}
.work-dialog{width:min(720px,96vw);border-radius:18px}.dialog-heading{display:flex;align-items:flex-start;justify-content:space-between;padding:24px 26px 18px;border-bottom:1px solid var(--app-border)}.dialog-eyebrow{text-transform:uppercase;letter-spacing:.13em;color:var(--app-accent);font-size:9px;font-weight:800;margin-bottom:5px}.dialog-body{padding:24px 26px}.dialog-actions{padding:16px 26px 22px;border-top:1px solid var(--app-border)}.dialog-actions .q-btn{border-radius:10px}.field-label{font-size:12px;font-weight:700;color:var(--app-text)}.ai-note{display:flex;align-items:center;gap:12px;padding:13px 15px;border-radius:11px;background:var(--app-purple-bg);color:var(--app-purple-text)}.ai-note>.q-icon{font-size:27px}.ai-note b,.ai-note span{display:block;font-size:11px}.ai-note span{opacity:.75;margin-top:2px}
</style>
