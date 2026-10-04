<script setup lang="ts">
import { reactive } from 'vue'

defineProps<{ loading: boolean }>()
const emit = defineEmits<{ login: [login: string, pin: string] }>()
const form = reactive({ login: 'master', pin: '1111' })
</script>

<template>
  <div class="login-screen">
    <section class="login-story">
      <div class="brand-mark"><q-icon name="precision_manufacturing" size="34px" /></div>
      <div class="story-copy">
        <div class="eyebrow">Костанайские минералы</div>
        <h1>Работы под контролем.<br><span>Без бумажной волокиты.</span></h1>
        <p>Выдавайте наряды, следите за сроками и принимайте выполненные работы с локальной AI-проверкой.</p>
      </div>
      <div class="system-state"><span class="pulse" /> Локальный контур · данные внутри предприятия</div>
    </section>

    <section class="login-panel">
      <q-form class="login-form" @submit.prevent="emit('login', form.login, form.pin)">
        <div class="mobile-brand"><q-icon name="precision_manufacturing" /> НарядAI</div>
        <div class="eyebrow text-primary">Рабочая смена</div>
        <h2>Вход в систему</h2>
        <p class="intro">Используйте персональный логин и PIN-код.</p>
        <q-input v-model="form.login" outlined autofocus label="Логин" autocomplete="username" class="field">
          <template #prepend><q-icon name="badge" /></template>
        </q-input>
        <q-input v-model="form.pin" outlined type="password" inputmode="numeric" maxlength="8" label="PIN-код" autocomplete="current-password" class="field" :rules="[v => /^\d{4,8}$/.test(v) || 'Введите от 4 до 8 цифр']">
          <template #prepend><q-icon name="pin" /></template>
        </q-input>
        <q-btn unelevated no-caps color="primary" size="lg" class="full-width login-button" type="submit" label="Войти в смену" icon-right="arrow_forward" :loading="loading" />
        <div class="demo-access"><q-icon name="info" /><span>Демо-доступ: <b>master / 1111</b> или <b>worker / 2222</b></span></div>
      </q-form>
    </section>
  </div>
</template>

<style scoped>
.login-screen{min-height:100vh;display:grid;grid-template-columns:minmax(420px,1.15fr) minmax(420px,.85fr);background:#f4f7f5}.login-story{position:relative;overflow:hidden;display:flex;flex-direction:column;justify-content:space-between;padding:54px 64px;color:#fff;background:linear-gradient(145deg,#071d18 0%,#123e31 58%,#1d6548 100%)}.login-story:before{content:"";position:absolute;width:520px;height:520px;border:1px solid rgb(255 255 255/9%);border-radius:50%;right:-180px;top:-160px;box-shadow:0 0 0 75px rgb(255 255 255/3%),0 0 0 150px rgb(255 255 255/2%)}.brand-mark{position:relative;width:64px;height:64px;display:grid;place-items:center;border:1px solid rgb(255 255 255/22%);border-radius:18px;background:rgb(255 255 255/9%)}.story-copy{position:relative;max-width:680px}.eyebrow{text-transform:uppercase;letter-spacing:.16em;font-weight:700;font-size:12px;color:#9ed5b7}.story-copy h1{font-size:clamp(42px,5vw,72px);line-height:1.03;letter-spacing:-.045em;margin:18px 0 26px}.story-copy h1 span{color:#8bd2aa}.story-copy p{max-width:590px;font-size:18px;line-height:1.65;color:rgb(255 255 255/70%)}.system-state{position:relative;display:flex;align-items:center;gap:10px;color:rgb(255 255 255/66%);font-size:13px}.pulse{width:9px;height:9px;border-radius:50%;background:#65d596;box-shadow:0 0 0 5px rgb(101 213 150/12%)}.login-panel{display:grid;place-items:center;padding:48px}.login-form{width:min(420px,100%)}.login-form h2{font-size:36px;letter-spacing:-.03em;margin:10px 0 6px;color:#13251f}.intro{margin:0 0 32px;color:#6a7771}.field{margin-bottom:12px}.login-button{height:56px;border-radius:12px;font-weight:700;margin-top:6px}.demo-access{display:flex;gap:10px;align-items:flex-start;margin-top:24px;padding:14px 16px;border-radius:12px;background:#e9f1ed;color:#52635b;font-size:13px}.mobile-brand{display:none;font-weight:800;font-size:20px;color:#174d3a;margin-bottom:48px}.mobile-brand .q-icon{font-size:28px;margin-right:6px}@media(max-width:850px){.login-screen{grid-template-columns:1fr}.login-story{display:none}.login-panel{padding:28px}.mobile-brand{display:block}}
</style>
