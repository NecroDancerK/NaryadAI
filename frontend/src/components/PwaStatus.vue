<script setup lang="ts">
/// <reference types="vite-plugin-pwa/client" />
import { onMounted, ref } from 'vue'
import { registerSW } from 'virtual:pwa-register'

const props = defineProps<{ blocked: boolean }>()
const updateReady = ref(false)
const reloadReady = ref(false)
const registrationFailed = ref(false)
let reloadRequested = false
let activate: () => Promise<void> = async () => {}
onMounted(() => {
  if (!window.isSecureContext || !('serviceWorker' in navigator)) {
    registrationFailed.value = true
    return
  }
  activate = registerSW({
    immediate: true,
    onNeedRefresh: () => { updateReady.value = true },
    onNeedReload: () => {
      reloadReady.value = true
      updateReady.value = true
      // Another tab may activate the worker. Never discard this tab's form automatically.
      if (reloadRequested && !props.blocked) window.location.reload()
    },
    onRegisterError: () => { registrationFailed.value = true },
  })
})
async function update() {
  if (props.blocked) return
  if (reloadReady.value) { window.location.reload(); return }
  reloadRequested = true
  try { await activate() }
  catch { reloadRequested = false; registrationFailed.value = true }
}
</script>
<template>
  <q-banner v-if="updateReady || registrationFailed" class="pwa-status" role="status">
    {{ updateReady ? 'Доступно обновление приложения.' : 'Не удалось подготовить офлайн-запуск. Проверьте HTTPS и перезагрузите страницу при наличии сети.' }}
    <span v-if="updateReady && blocked"> Сначала завершите действие и закройте форму.</span>
    <template #action><q-btn v-if="updateReady" flat no-caps label="Обновить приложение" :disable="blocked" @click="update" /></template>
  </q-banner>
</template>
<style scoped>
.pwa-status{position:fixed;bottom:80px;left:16px;right:16px;z-index:7000;max-width:620px;margin:auto;border:1px solid var(--app-border);border-radius:12px;background:var(--app-surface);color:var(--app-text);box-shadow:0 4px 20px #0002}
</style>
