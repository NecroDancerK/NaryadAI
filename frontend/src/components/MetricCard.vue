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
.metric-card{display:flex;align-items:center;gap:15px;min-height:108px;padding:20px;background:#fff;border:1px solid #e0e7e3;border-radius:16px;box-shadow:0 2px 7px rgb(19 52 40/3%)}.metric-icon{width:48px;height:48px;display:grid;place-items:center;border-radius:13px;font-size:25px}.tone-green{background:#e4f4eb;color:#14814c}.tone-amber{background:#fff2d9;color:#b76a00}.tone-red{background:#fde8e6;color:#c53c32}.tone-blue{background:#e4edf8;color:#306aa4}.metric-value{font-size:28px;line-height:1;font-weight:800;letter-spacing:-.03em;color:#1a2822}.metric-label{font-size:13px;color:#5f6e67;margin-top:6px}.metric-hint{font-size:10px;color:#98a29d;margin-top:2px}
</style>
