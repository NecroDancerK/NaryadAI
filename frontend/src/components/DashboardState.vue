<script setup lang="ts">
defineProps<{loading: boolean; error?: string; offline?: boolean; hasData: boolean}>()
const emit = defineEmits<{retry: []}>()
</script>
<template>
<div class="dashboard-state" aria-live="polite">
<q-banner v-if="offline" rounded class="bg-amber-1 text-brown-9 q-mb-md"><template #avatar><q-icon name="cloud_off"/></template>Нет сети. {{ hasData ? 'Показаны ранее загруженные данные.' : 'Данные ещё не загружены. Подключитесь к сети.' }} Действия исполнителя сохраняются на устройстве.</q-banner>
<q-banner v-if="error" rounded class="bg-red-1 text-negative q-mb-md"><template #avatar><q-icon name="error_outline"/></template>{{ hasData ? 'Не удалось обновить данные. Показана последняя версия.' : 'Не удалось загрузить данные.' }} {{ error }}<template #action><q-btn flat no-caps label="Повторить" @click="emit('retry')"/></template></q-banner>
<div v-if="loading && !hasData && !error && !offline" class="loading-grid" :aria-busy="true"><span class="sr-only">Загрузка данных</span><q-skeleton v-for="n in 3" :key="n" height="140px" animation="wave"/></div>
</div>
</template>
<style scoped>
.loading-grid{display:grid;gap:12px;margin-bottom:20px}.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}
</style>
