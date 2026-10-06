<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { date } from 'quasar'
import type { Directories } from '../api'

const props = defineProps<{ modelValue: boolean; directories?: Directories; loading: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; submit: [payload: { data: Record<string, unknown>; photos: File[] }] }>()

const form = reactive({ description: '', work_type: 'unplanned', site_id: 1, equipment_id: 1, assignee_id: 2, priority: 'normal', due_at: '' })
const photos = ref<File[]>([])
const workers = computed(() => props.directories?.users.filter(user => user.role === 'worker') ?? [])
const equipment = computed(() => props.directories?.equipment.filter(item => item.site_id === form.site_id) ?? [])

function reset() {
  form.description = ''
  form.work_type = 'unplanned'
  form.site_id = props.directories?.sites[0]?.id ?? 1
  form.equipment_id = equipment.value[0]?.id ?? 1
  form.assignee_id = workers.value[0]?.id ?? 2
  form.priority = 'normal'
  form.due_at = date.formatDate(Date.now() + 7_200_000, 'YYYY-MM-DDTHH:mm')
  photos.value = []
}

watch(() => props.modelValue, value => { if (value) reset() })
watch(() => form.site_id, () => { form.equipment_id = equipment.value[0]?.id ?? 0 })

function submit() {
  emit('submit', { data: { ...form, due_at: new Date(form.due_at).toISOString() }, photos: photos.value })
}
</script>

<template>
  <q-dialog :model-value="modelValue" persistent @update:model-value="emit('update:modelValue', $event)">
    <q-card class="work-dialog">
      <q-card-section class="dialog-heading"><div><div class="dialog-eyebrow">Планирование работ</div><div class="text-h5 text-weight-bold">Новый наряд</div></div><q-btn flat round icon="close" @click="emit('update:modelValue', false)" /></q-card-section>
      <q-form @submit.prevent="submit">
        <q-card-section class="dialog-body q-gutter-md">
          <q-input v-model="form.description" outlined autogrow label="Что нужно сделать *" :rules="[value => value.length >= 5 || 'Опишите работу подробнее']" />
          <div class="row q-col-gutter-md"><q-select v-model="form.work_type" class="col-12 col-sm-6" outlined emit-value map-options label="Тип работы *" :options="[{label:'Внеплановая',value:'unplanned'},{label:'Плановая',value:'planned'}]"/><q-select v-model="form.priority" class="col-12 col-sm-6" outlined emit-value map-options label="Приоритет" :options="[{label:'Аварийный',value:'emergency'},{label:'Высокий',value:'high'},{label:'Обычный',value:'normal'},{label:'Плановый',value:'planned'}]"/></div>
          <div class="row q-col-gutter-md"><q-select v-model="form.site_id" class="col-12 col-sm-6" outlined emit-value map-options label="Участок *" :options="directories?.sites" option-value="id" option-label="name"/><q-select v-model="form.equipment_id" class="col-12 col-sm-6" outlined emit-value map-options label="Оборудование *" :options="equipment" option-value="id" option-label="name"/></div>
          <q-select v-model="form.assignee_id" outlined emit-value map-options label="Исполнитель *" :options="workers" option-value="id" option-label="full_name"/>
          <q-input v-model="form.due_at" outlined type="datetime-local" label="Срок исполнения *"><template #prepend><q-icon name="event"/></template></q-input>
          <q-file v-model="photos" outlined multiple accept="image/*" max-files="5" max-file-size="10485760" label="Фото неисправности, до 5"><template #prepend><q-icon name="photo_camera"/></template></q-file>
        </q-card-section>
        <q-card-actions align="right" class="dialog-actions"><q-btn flat no-caps label="Отмена" @click="emit('update:modelValue', false)"/><q-btn unelevated no-caps color="primary" type="submit" icon="send" label="Выдать наряд" :loading="loading"/></q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<style scoped>
.work-dialog{width:min(700px,96vw);border-radius:18px}.dialog-heading{display:flex;align-items:center;justify-content:space-between;padding:24px 26px 18px;border-bottom:1px solid #e7ece9}.dialog-eyebrow{text-transform:uppercase;letter-spacing:.13em;color:#3c8262;font-size:9px;font-weight:800;margin-bottom:5px}.dialog-body{padding:24px 26px}.dialog-actions{padding:16px 26px 22px;border-top:1px solid #eef1ef}.dialog-actions .q-btn{min-width:130px;border-radius:10px}
</style>
