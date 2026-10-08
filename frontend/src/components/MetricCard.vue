<script setup lang="ts">
defineProps<{ label: string; value: string | number; icon: string; tone: 'green' | 'amber' | 'red' | 'blue'; hint?: string }>()
</script>

<template>
  <div class="metric-card">
    <div :class="['metric-icon', `tone-${tone}`]"><q-icon :name="icon" /></div>
    <div><div class="metric-value">{{ value }}</div><div class="metric-label">{{ label }}</div><div v-if="hint" class="metric-hint">{{ hint }}</div></div>
  </div>
</template>

<style scoped>
.metric-card{display:flex;align-items:center;gap:15px;min-height:108px;padding:20px;background:var(--app-surface);border:1px solid var(--app-border);border-radius:16px;box-shadow:0 2px 7px rgb(19 52 40/3%)}.metric-icon{width:48px;height:48px;display:grid;place-items:center;border-radius:13px;font-size:25px}.tone-green{background:var(--app-green-bg);color:var(--app-green-text)}.tone-amber{background:var(--app-amber-bg);color:var(--app-amber-text)}.tone-red{background:var(--app-red-bg);color:var(--app-red-text)}.tone-blue{background:var(--app-blue-bg);color:var(--app-blue-text)}.metric-value{font-size:28px;line-height:1;font-weight:800;letter-spacing:-.03em;color:var(--app-text)}.metric-label{font-size:13px;color:var(--app-muted);margin-top:6px}.metric-hint{font-size:10px;color:var(--app-muted);margin-top:2px}
</style>
<style scoped>
.metric-icon{flex:0 0 48px}.metric-card>div:last-child{min-width:0}.metric-label,.metric-hint{overflow-wrap:anywhere}
@media(max-width:599px){.metric-card{gap:10px;padding:14px 12px;min-height:96px}.metric-icon{flex-basis:36px;width:36px;height:36px;font-size:22px;border-radius:10px}.metric-value{font-size:25px}.metric-label{font-size:12px}}
</style>
