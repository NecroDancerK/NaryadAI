<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import type { Directories, WorkOrder } from '../api'

const props = defineProps<{ modelValue: boolean; order?: WorkOrder; directories?: Directories; loading: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; submit: [data: FormData] }>()
const form = reactive({ work_performed: '', fault_code_id: 1, material_id: null as number | null, quantity: 1, photo: null as File | null, comment: '' })
const usages = ref<Array<{ material_id: number; quantity: number }>>([])

watch(() => props.modelValue, value => {
  if (!value) return
  form.work_performed = ''; form.fault_code_id = props.directories?.fault_codes[0]?.id ?? 1
  form.material_id = null; form.quantity = 1; form.photo = null; form.comment = ''; usages.value = []
})

function materialName(id: number) { return props.directories?.materials.find(item => item.id === id)?.name ?? `#${id}` }
function addMaterial() {
  if (!form.material_id || form.quantity <= 0) return
  const existing = usages.value.find(item => item.material_id === form.material_id)
  if (existing) existing.quantity += form.quantity
  else usages.value.push({ material_id: form.material_id, quantity: form.quantity })
  form.material_id = null; form.quantity = 1
}
function submit() {
  const data = new FormData()
  data.append('work_performed', form.work_performed)
  data.append('fault_code_id', String(form.fault_code_id))
  data.append('materials_json', JSON.stringify(usages.value))
  if (form.comment) data.append('comment', form.comment)
  if (form.photo) data.append('photo', form.photo)
  emit('submit', data)
}
</script>

<template>
  <q-dialog :model-value="modelValue" persistent @update:model-value="emit('update:modelValue', $event)">
    <q-card class="work-dialog">
      <q-card-section class="dialog-heading"><div><div class="dialog-eyebrow">Результат работ</div><div class="text-h5 text-weight-bold">Закрытие {{ order?.number }}</div><div class="text-caption text-grey-7">Зафиксируйте фактически выполненные работы</div></div><q-btn flat round icon="close" @click="emit('update:modelValue', false)"/></q-card-section>
      <q-form @submit.prevent="submit">
        <q-card-section class="dialog-body q-gutter-md">
          <q-input v-model="form.work_performed" outlined autogrow label="Выполненные работы *" :rules="[value => value.length >= 5 || 'Опишите выполненные работы']"/>
          <q-select v-model="form.fault_code_id" outlined emit-value map-options label="Шифр неисправности *" :options="directories?.fault_codes" option-value="id" :option-label="item => `${item.code} — ${item.name}`"/>
          <div class="field-label">Списанные материалы</div><div class="row q-col-gutter-sm"><q-select v-model="form.material_id" class="col" outlined dense emit-value map-options clearable label="Материал" :options="directories?.materials" option-value="id" :option-label="item => `${item.name}, ${item.unit}`"/><q-input v-model.number="form.quantity" class="col-3" outlined dense type="number" min="0.001" step="0.001" label="Кол-во"/><div class="col-auto"><q-btn round unelevated color="primary" icon="add" @click="addMaterial"/></div></div>
          <q-list v-if="usages.length" bordered separator class="rounded-borders"><q-item v-for="(usage,index) in usages" :key="usage.material_id"><q-item-section>{{ materialName(usage.material_id) }}</q-item-section><q-item-section side>{{ usage.quantity }}</q-item-section><q-item-section side><q-btn flat round dense icon="delete_outline" color="negative" @click="usages.splice(index,1)"/></q-item-section></q-item></q-list>
          <q-file v-model="form.photo" outlined accept="image/*" capture="environment" :label="order?.work_type==='unplanned'?'Фото после ремонта *':'Фото после ремонта'" max-file-size="10485760"><template #prepend><q-icon name="photo_camera"/></template></q-file>
          <q-input v-model="form.comment" outlined autogrow label="Комментарий"/>
          <div class="ai-note"><q-icon name="neurology"/><div><b>Далее — автоматическая проверка</b><span>Локальная модель сопоставит задание и результат работ.</span></div></div>
        </q-card-section>
        <q-card-actions align="right" class="dialog-actions"><q-btn flat no-caps label="Отмена" @click="emit('update:modelValue', false)"/><q-btn unelevated no-caps color="positive" type="submit" icon="task_alt" label="Отправить на проверку" :loading="loading"/></q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<style scoped>
.work-dialog{width:min(720px,96vw);border-radius:18px}.dialog-heading{display:flex;align-items:flex-start;justify-content:space-between;padding:24px 26px 18px;border-bottom:1px solid #e7ece9}.dialog-eyebrow{text-transform:uppercase;letter-spacing:.13em;color:#3c8262;font-size:9px;font-weight:800;margin-bottom:5px}.dialog-body{padding:24px 26px}.dialog-actions{padding:16px 26px 22px;border-top:1px solid #eef1ef}.dialog-actions .q-btn{border-radius:10px}.field-label{font-size:12px;font-weight:700;color:#43534b}.ai-note{display:flex;align-items:center;gap:12px;padding:13px 15px;border-radius:11px;background:#f0ebf8;color:#563d75}.ai-note>.q-icon{font-size:27px}.ai-note b,.ai-note span{display:block;font-size:11px}.ai-note span{opacity:.75;margin-top:2px}
</style>
