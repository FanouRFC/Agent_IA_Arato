<script setup lang="ts">
import { onMounted, ref } from 'vue'
/** Barres horizontales animées (libellé, valeur, détail au survol). */
export interface Bar { label: string; value: number; color?: string; hint?: string }
defineProps<{ items: Bar[]; max?: number; unit?: string }>()
const ready = ref(false)
onMounted(() => requestAnimationFrame(() => (ready.value = true)))
</script>
<template>
  <ul class="space-y-3">
    <li v-for="b in items" :key="b.label" class="group" :title="b.hint">
      <div class="mb-1 flex items-baseline justify-between gap-3 text-xs">
        <span class="truncate font-medium text-slate-700">{{ b.label }}</span>
        <span class="shrink-0 tabular-nums text-slate-500"><b class="text-slate-900">{{ b.value }}</b>{{ unit }}</span>
      </div>
      <div class="h-2.5 overflow-hidden rounded-full bg-slate-100">
        <div class="h-full rounded-full transition-all duration-700 ease-out group-hover:brightness-110"
          :style="{ width: ready ? Math.min(100, (b.value / (max || Math.max(1, ...items.map((x) => x.value)))) * 100) + '%' : '0%', background: b.color || '#223E67' }" />
      </div>
    </li>
  </ul>
</template>
