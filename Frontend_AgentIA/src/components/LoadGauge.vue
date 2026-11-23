<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import Avatar from '@/components/Avatar.vue'

/** Jauge circulaire fine autour de la photo d'un membre : l'arc se remplit selon la charge (animé à l'affichage). */
const props = withDefaults(defineProps<{ nom: string; photo?: string | null; value: number; color: string; size?: number }>(), { size: 68 })
const stroke = 4
const r = computed(() => (props.size - stroke) / 2)
const circ = computed(() => 2 * Math.PI * r.value)
const ready = ref(false)
onMounted(() => requestAnimationFrame(() => (ready.value = true)))
const dash = computed(() => `${ready.value ? Math.max(0, Math.min(1, props.value)) * circ.value : 0} ${circ.value}`)
</script>

<template>
  <div class="relative grid shrink-0 place-items-center" :style="{ width: size + 'px', height: size + 'px' }">
    <svg :width="size" :height="size" :viewBox="`0 0 ${size} ${size}`" class="absolute inset-0 -rotate-90" aria-hidden="true">
      <circle :cx="size / 2" :cy="size / 2" :r="r" fill="none" stroke="#E3E8F0" :stroke-width="stroke" />
      <circle :cx="size / 2" :cy="size / 2" :r="r" fill="none" :stroke="color" :stroke-width="stroke" stroke-linecap="round"
        :stroke-dasharray="dash" class="transition-all duration-1000 ease-out" />
    </svg>
    <Avatar :nom="nom" :src="photo" :size="size - 16" calm />
  </div>
</template>
