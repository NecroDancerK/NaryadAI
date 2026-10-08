<script setup lang="ts">
import { computed, ref } from 'vue'
import { themeMode } from '../theme'
import type { ThemeMode } from '../utils/themePreference'
const open = ref(false)
const options: Array<{value: ThemeMode; label: string; icon: string}> = [
  { value: 'light', label: 'Светлая', icon: 'light_mode' },
  { value: 'dark', label: 'Тёмная', icon: 'dark_mode' },
  { value: 'system', label: 'Как в системе', icon: 'settings_brightness' },
]
const selected = computed(() => options.find(option => option.value === themeMode.value)!)
function choose(mode: ThemeMode) { themeMode.value = mode; open.value = false }
</script>
<template>
  <q-btn flat round :icon="selected.icon" :aria-label="`Тема: ${selected.label}`" :title="`Тема: ${selected.label}`">
    <q-menu v-model="open" anchor="bottom right" self="top right">
      <q-list padding style="min-width: 210px">
        <q-item-label header>Оформление</q-item-label>
        <q-item v-for="option in options" :key="option.value" class="theme-option" clickable :active="themeMode === option.value" @click="choose(option.value)">
          <q-item-section avatar><q-icon :name="option.icon" /></q-item-section>
          <q-item-section>{{ option.label }}</q-item-section>
          <q-item-section side><q-icon v-if="themeMode === option.value" name="check" color="primary" /></q-item-section>
        </q-item>
      </q-list>
    </q-menu>
  </q-btn>
</template>
<style scoped>
.theme-option.q-item--active { color: var(--app-accent); }
</style>
