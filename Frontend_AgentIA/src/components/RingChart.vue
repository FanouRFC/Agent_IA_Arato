<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
/** Anneau (donut) interactif : survol d'un segment = son détail au centre. Sans dépendance. */
export interface Seg { label: string; value: number; color: string }
const props = withDefaults(defineProps<{ segments: Seg[]; size?: number; thickness?: number; center?: string; caption?: string }>(), { size: 168, thickness: 18 })
const hover = ref<number | null>(null)
const ready = ref(false)
onMounted(() => requestAnimationFrame(() => (ready.value = true)))
const r = computed(() => (props.size - props.thickness) / 2)
const circ = computed(() => 2 * Math.PI * r.value)
const total = computed(() => props.segments.reduce((s, x) => s + Math.max(0, x.value), 0))
const arcs = computed(() => {
  let acc = 0
  return props.segments.map((s, i) => {
    const frac = total.value ? Math.max(0, s.value) / total.value : 0
    const a = { i, len: frac * circ.value, off: -acc * circ.value, color: s.color }
    acc += frac
    return a
  })
})
const centerValue = computed(() => (hover.value !== null ? String(props.segments[hover.value]?.value ?? '') : props.center ?? String(total.value)))
const centerLabel = computed(() => (hover.value !== null ? props.segments[hover.value]?.label ?? '' : props.caption ?? ''))
</script>
<template>
  <div class="relative inline-grid place-items-center" :style="{ width: size + 'px', height: size + 'px' }">
    <svg :width="size" :height="size" :viewBox="`0 0 ${size} ${size}`" class="-rotate-90">
      <circle :cx="size / 2" :cy="size / 2" :r="r" fill="none" stroke="#E3E8F0" :stroke-width="thickness" />
      <circle v-for="a in arcs" :key="a.i" :cx="size / 2" :cy="size / 2" :r="r" fill="none" :stroke="a.color"
        :stroke-width="hover === a.i ? thickness + 4 : thickness" stroke-linecap="butt"
        :stroke-dasharray="`${ready ? Math.max(0, a.len - (arcs.length > 1 && a.len > 3 ? 2 : 0)) : 0} ${circ}`" :stroke-dashoffset="a.off"
        class="cursor-pointer transition-all duration-700 ease-out" :opacity="hover === null || hover === a.i ? 1 : 0.35"
        @mouseenter="hover = a.i" @mouseleave="hover = null" />
    </svg>
    <div class="pointer-events-none absolute inset-0 grid place-content-center text-center">
      <p class="display text-3xl leading-none tabular-nums text-slate-900">{{ centerValue }}</p>
      <p v-if="centerLabel" class="mt-1 max-w-[7rem] text-[11px] leading-tight text-slate-500">{{ centerLabel }}</p>
    </div>
  </div>
</template>
