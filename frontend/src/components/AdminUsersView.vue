<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { useQuasar } from 'quasar'
import { api, type AdminUser, type CurrentUser, type UserRole } from '../api'
import { roleLabels, roleOptions } from '../utils/roles'

const props = defineProps<{user:CurrentUser;online:boolean}>()
const emit = defineEmits<{ 'session-revoked':[] }>()
const $q = useQuasar()
const client = useQueryClient()
const offset = ref(0)
const auditOffset = ref(0)
const enabled = computed(() => props.online && props.user.role === 'admin')
const users = useQuery({queryKey:computed(() => ['admin-users',props.user.id,offset.value]),queryFn:()=>api.adminUsers(offset.value),enabled})
const audit = useQuery({queryKey:computed(() => ['admin-audit',props.user.id,auditOffset.value]),queryFn:()=>api.adminAudit(auditOffset.value),enabled})
const dialog = ref(false)
const editingId = ref<number|null>(null)
const editingAccount = ref<AdminUser|null>(null)
const form = reactive({login:'',full_name:'',role:'worker' as UserRole,specialty:'',pin:''})
const pinTarget = ref<AdminUser|null>(null)
const newPin = ref('')
watch(dialog, value => { if (!value) form.pin = '' })
watch(pinTarget, value => { if (!value) newPin.value = '' })
const busy = computed(() => save.isPending.value || toggle.isPending.value || reset.isPending.value)
function refresh() {
  client.invalidateQueries({queryKey:['admin-users']})
  client.invalidateQueries({queryKey:['admin-audit']})
  client.invalidateQueries({queryKey:['directories']})
  client.invalidateQueries({queryKey:['shift-workers']})
}
function notify(error:Error) { $q.notify({type:'negative',message:error.message}); refresh() }
function edit(user?:AdminUser) {
  editingId.value = user?.id ?? null
  editingAccount.value = user ? {...user} : null
  Object.assign(form,{login:user?.login ?? '',full_name:user?.full_name ?? '',role:user?.role ?? 'worker',specialty:user?.specialty ?? '',pin:''})
  dialog.value = true
}
const save = useMutation({
  mutationFn:async () => {
    if (!props.online) throw new Error('Управление пользователями доступно только при соединении с сервером')
    const payload = {full_name:form.full_name.trim(),role:form.role,specialty:form.role==='worker' ? form.specialty.trim() || null : null}
    if (editingId.value===null) return api.createUser({...payload,login:form.login.trim(),pin:form.pin})
    const user = editingAccount.value
    if (!user) throw new Error('Обновите список пользователей')
    return api.updateUser(user.id,{...payload,is_active:user.is_active,expected_session_version:user.session_version})
  },
  onSuccess:()=>{dialog.value=false;form.pin='';refresh();$q.notify({type:'positive',message:'Пользователь сохранён'})},onError:notify,
})
const toggle = useMutation({
  mutationFn:(user:AdminUser)=>{
    if (!props.online) throw new Error('Нет соединения с сервером')
    return api.updateUser(user.id,{full_name:user.full_name,role:user.role,specialty:user.specialty,is_active:!user.is_active,expected_session_version:user.session_version})
  },onSuccess:()=>{refresh();$q.notify({type:'positive',message:'Доступ пользователя изменён'})},onError:notify,
})
function confirmAccess(user:AdminUser) {
  $q.dialog({title:user.is_active?'Заблокировать пользователя?':'Восстановить доступ?',message:`${user.full_name} (${user.login}). ${user.is_active?'Сессии будут отозваны. Наряды и история сохранятся.':'Для входа понадобится действующий PIN.'}`,cancel:true,persistent:true})
    .onOk(()=>toggle.mutate(user))
}
const reset = useMutation({
  mutationFn:({id,pin,version}:{id:number;pin:string;version:number})=>{
    if (!props.online) throw new Error('Нет соединения с сервером')
    return api.resetPin(id,pin,version)
  },onSuccess:(_,input)=>{
    pinTarget.value=null;newPin.value='';refresh()
    $q.notify({type:'positive',message:'PIN изменён, прежние сессии отозваны'})
    if (input.id===props.user.id) emit('session-revoked')
  },onError:notify,
})
const pinRule = (value:string) => /^[0-9]{6,8}$/.test(value) || 'Введите от 6 до 8 цифр'
const actions:Record<string,string> = {'user.created':'Создание пользователя','user.updated':'Изменение пользователя','user.pin_reset':'Сброс PIN','admin.bootstrapped':'Создание первого администратора'}
</script>

<template>
  <section class="admin-view">
    <div class="page-heading"><div><div class="eyebrow">Управление доступом</div><h1>Пользователи</h1><p>Роли, блокировка и отзыв сессий. Наряды и журнал сохраняются.</p></div><q-btn color="primary" no-caps icon="person_add" label="Добавить пользователя" :disable="!online || busy" @click="edit()" /></div>
    <q-banner v-if="!online" rounded class="q-mb-md">Нет соединения. Изменения пользователей не ставятся в offline-очередь.</q-banner>
    <q-banner v-if="users.error.value" rounded class="q-mb-md">{{ users.error.value.message }}<template #action><q-btn flat no-caps label="Повторить" :disable="!online" @click="users.refetch()" /></template></q-banner>
    <q-card flat bordered class="users-card">
      <q-card-section v-if="users.isPending.value && online"><q-spinner /> Загрузка пользователей…</q-card-section>
      <q-list separator>
        <q-item v-for="account in users.data.value" :key="account.id" class="account-row">
          <q-item-section><q-item-label class="account-name">{{ account.full_name }} <q-badge v-if="account.id===user.id" outline color="primary">Вы</q-badge></q-item-label><q-item-label caption>{{ account.login }} · {{ roleLabels[account.role] }}<span v-if="account.specialty"> · {{ account.specialty }}</span></q-item-label><q-item-label caption>{{ account.is_active?'Доступ разрешён':'Заблокирован' }}</q-item-label></q-item-section>
          <q-item-section side class="account-actions"><div><q-btn flat no-caps icon="edit" label="Изменить" :disable="!online || busy" @click="edit(account)"/><q-btn flat no-caps icon="key" label="Сброс PIN" :disable="!online || busy" @click="pinTarget=account;newPin=''"/><q-btn flat no-caps :color="account.is_active?'negative':'primary'" :icon="account.is_active?'block':'lock_open'" :label="account.is_active?'Блокировать':'Разблокировать'" :disable="!online || busy || account.id===user.id" @click="confirmAccess(account)"/></div></q-item-section>
        </q-item>
        <q-item v-if="users.isSuccess.value && !users.data.value?.length"><q-item-section>Пользователей на этой странице нет</q-item-section></q-item>
      </q-list>
    </q-card>
    <div class="pager"><q-btn flat no-caps label="Назад" :disable="offset===0 || users.isFetching.value" @click="offset=Math.max(0,offset-50)"/><span>Страница {{ offset/50+1 }}</span><q-btn flat no-caps label="Далее" :disable="users.data.value?.length!==50 || users.isFetching.value" @click="offset+=50"/></div>
    <h2>Журнал администрирования</h2>
    <q-banner v-if="audit.error.value" rounded>{{ audit.error.value.message }}<template #action><q-btn flat label="Повторить" :disable="!online" @click="audit.refetch()" /></template></q-banner>
    <q-card flat bordered><q-list separator><q-item v-for="event in audit.data.value" :key="event.id"><q-item-section><q-item-label>{{ actions[event.action] ?? event.action }}</q-item-label><q-item-label caption>{{ new Date(event.created_at).toLocaleString('ru-RU') }} · Автор #{{ event.actor_id }} · Пользователь #{{ event.target_id }}</q-item-label><pre class="audit-changes">{{ JSON.stringify(event.changes,null,2) }}</pre></q-item-section></q-item><q-item v-if="audit.isSuccess.value && !audit.data.value?.length"><q-item-section>Записей пока нет</q-item-section></q-item></q-list></q-card>
    <div class="pager"><q-btn flat no-caps label="Назад" :disable="auditOffset===0 || audit.isFetching.value" @click="auditOffset=Math.max(0,auditOffset-50)"/><span>Страница {{ auditOffset/50+1 }}</span><q-btn flat no-caps label="Далее" :disable="audit.data.value?.length!==50 || audit.isFetching.value" @click="auditOffset+=50"/></div>
    <q-dialog v-model="dialog" persistent>
      <q-card class="account-dialog"><q-form @submit.prevent="save.mutate()"><q-card-section><h2>{{ editingId===null?'Новый пользователь':'Изменить пользователя' }}</h2><q-input v-model="form.login" outlined label="Логин" :disable="editingId!==null || busy" :rules="[v=>/^[a-zA-Z0-9][a-zA-Z0-9._-]{1,79}$/.test(v)||'2–80 символов: латиница, цифры, ._-']"/><q-input v-model="form.full_name" outlined label="ФИО" maxlength="160" :disable="busy" :rules="[v=>v.trim().length>=2||'Введите имя']"/><q-select v-model="form.role" outlined emit-value map-options :options="roleOptions" label="Роль" :disable="busy || editingId===user.id"/><q-input v-if="form.role==='worker'" v-model="form.specialty" outlined label="Специальность" maxlength="100" :disable="busy"/><q-input v-if="editingId===null" v-model="form.pin" outlined type="password" inputmode="numeric" autocomplete="new-password" maxlength="8" label="PIN (6–8 цифр)" :disable="busy" :rules="[pinRule]"/><p>Смена роли отзывает сессии. Если есть незакрытые наряды, смена роли недоступна.</p></q-card-section><q-card-actions align="right"><q-btn flat no-caps label="Отмена" :disable="busy" @click="dialog=false"/><q-btn color="primary" no-caps label="Сохранить" type="submit" :loading="save.isPending.value" :disable="!online || busy"/></q-card-actions></q-form></q-card>
    </q-dialog>
    <q-dialog :model-value="pinTarget!==null" persistent>
      <q-card class="account-dialog"><q-form @submit.prevent="pinTarget && reset.mutate({id:pinTarget.id,pin:newPin,version:pinTarget.session_version})"><q-card-section><h2>Новый PIN</h2><p>{{ pinTarget?.full_name }}. Все прежние сессии будут отозваны.</p><q-input v-model="newPin" outlined autofocus type="password" inputmode="numeric" autocomplete="new-password" maxlength="8" label="PIN (6–8 цифр)" :disable="busy" :rules="[pinRule]"/></q-card-section><q-card-actions align="right"><q-btn flat no-caps label="Отмена" :disable="busy" @click="pinTarget=null"/><q-btn color="primary" no-caps label="Сменить PIN" type="submit" :loading="reset.isPending.value" :disable="!online || busy"/></q-card-actions></q-form></q-card>
    </q-dialog>
  </section>
</template>

<style scoped>
.admin-view{max-width:1400px;margin:auto}.page-heading{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:24px}.page-heading h1{margin:6px 0;font-size:30px}.page-heading p,.account-dialog p{color:var(--app-muted)}.eyebrow{color:var(--app-accent);font-size:12px;text-transform:uppercase;letter-spacing:.12em}.account-name{font-weight:700}.account-row{padding:18px}.account-actions>div{display:flex;flex-wrap:wrap;justify-content:flex-end}.account-dialog{width:520px;max-width:95vw}.account-dialog .q-field{margin:12px 0}.pager{display:flex;align-items:center;justify-content:flex-end;gap:12px;margin:12px 0 24px}.audit-changes{font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere;color:var(--app-muted);margin:10px 0 0}h2{font-size:20px}@media(max-width:800px){.page-heading{align-items:flex-start;flex-direction:column}.account-row{flex-wrap:wrap}.account-actions{width:100%;padding-left:0;margin-top:12px;align-items:flex-start}.account-actions>div{justify-content:flex-start}.pager{justify-content:center}}
</style>
<style scoped>
@media(max-width:800px){
  .account-row{flex-direction:column;align-items:stretch}
  .account-row :deep(.q-item__section--main){width:100%;min-width:0}
  .account-actions{flex:none;min-width:0;margin-left:0;padding-left:0}
}
</style>
