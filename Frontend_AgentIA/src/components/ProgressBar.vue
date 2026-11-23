<script setup lang="ts">
withDefaults(defineProps<{ value: number; tone?: 'brand' | 'green' | 'amber' | 'red' | 'slate' }>(), { tone: 'brand' })
const TONES = {
  brand: 'bg-gradient-to-r from-brand-500 to-purple-500', green: 'bg-sky-400', amber: 'bg-purple-500', red: 'bg-red-500', slate: 'bg-sky-300',
}
</script>
<template>
  <div class="flex items-center gap-2" role="img" :aria-label="`Avancement déclaré ${value} %`">
    <div class="h-1.5 w-20 overflow-hidden rounded-full bg-slate-100">
      <div class="h-full rounded-full" :class="TONES[tone]" :style="{ width: Math.min(100, Math.max(0, value)) + '%' }" />
    </div>
    <span class="w-10 whitespace-nowrap text-xs tabular-nums text-slate-600">{{ value }} %</span>
  </div>
</template>
