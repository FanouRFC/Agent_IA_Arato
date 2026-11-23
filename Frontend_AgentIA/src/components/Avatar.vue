<script setup lang="ts">
import { computed } from 'vue'
import { initiales } from '@/services/api'

/** Photo de profil ; sans photo, initiales sur un dégradé de la palette (toujours le même pour un même nom). */
const props = withDefaults(defineProps<{ nom: string; src?: string | null; size?: number; ring?: boolean; calm?: boolean }>(), { size: 32 })
const GRADS = [
  ['#223E67', '#0B192F'], ['#1B355C', '#4F678B'], ['#0B192F', '#223E67'], ['#34507B', '#1B355C'], ['#223E67', '#4F8B89'],
]
const grad = computed(() => {
  let h = 0
  for (const c of props.nom) h = (h * 31 + c.charCodeAt(0)) >>> 0
  const [a, b] = GRADS[h % GRADS.length] as string[]
  return `linear-gradient(135deg, ${a}, ${b})`
})
</script>

<template>
  <span class="relative inline-grid shrink-0 place-items-center overflow-hidden rounded-full font-semibold text-white"
    :class="ring && 'ring-2 ring-white'" :style="{ width: size + 'px', height: size + 'px', fontSize: Math.max(10, size * 0.36) + 'px', background: src ? '#DFE4EC' : calm ? '#E3E8F0' : grad, color: calm && !src ? '#34507B' : undefined }"
    :title="nom">
    <img v-if="src" :src="src" :alt="nom" class="size-full object-cover" loading="lazy" />
    <template v-else>{{ initiales(nom) }}</template>
  </span>
</template>
