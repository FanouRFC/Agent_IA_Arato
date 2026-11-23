<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
/** Note en étoiles (0 à 5, demi-étoiles comprises), dégradé bleu → violet. Le remplissage s'anime à l'affichage. */
const props = withDefaults(defineProps<{ value: number; size?: number; label?: string }>(), { size: 22 })
const shown = ref(0)
onMounted(() => requestAnimationFrame(() => (shown.value = props.value)))
watch(() => props.value, (n) => (shown.value = n))      // les étoiles suivent la valeur à tout instant (0 = toutes grises)
const v = computed(() => Math.max(0, Math.min(5, shown.value)))
const pct = (i: number) => Math.max(0, Math.min(1, v.value - i)) * 100
const STAR = 'M12 2.6l2.85 6 6.55.8-4.8 4.55 1.25 6.5L12 17.2l-5.85 3.25 1.25-6.5L2.6 9.4l6.55-.8z'
const gid = `sg${Math.random().toString(36).slice(2, 8)}`
</script>
<template>
  <span class="inline-flex items-center gap-0.5" role="img" :aria-label="`${label ?? 'Note'} : ${value.toFixed(1)} sur 5`">
    <span v-for="i in 5" :key="i" class="relative inline-block" :style="{ width: size + 'px', height: size + 'px' }">
      <svg viewBox="0 0 24 24" :width="size" :height="size" class="absolute inset-0"><path :d="STAR" fill="#E3E8F0" stroke="#CCD1D8" stroke-width="1" stroke-linejoin="round" /></svg>
      <span class="absolute inset-y-0 left-0 overflow-hidden transition-[width] duration-700 ease-out" :style="{ width: pct(i - 1) + '%', transitionDelay: (i - 1) * 90 + 'ms' }">
        <svg viewBox="0 0 24 24" :width="size" :height="size" class="max-w-none">
          <defs><linearGradient :id="gid" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#4F8B89" /><stop offset="0.5" stop-color="#223E67" /><stop offset="1" stop-color="#1B355C" /></linearGradient></defs>
          <path :d="STAR" :fill="`url(#${gid})`" :stroke="`url(#${gid})`" stroke-width="1" stroke-linejoin="round" />
        </svg>
      </span>
    </span>
  </span>
</template>
