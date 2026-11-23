<script setup lang="ts">
import Icon from '@/components/Icon.vue'
defineProps<{ icon: string; title: string; text?: string }>()
</script>
<template>
  <div class="flex flex-col items-center px-6 py-12 text-center">
    <span class="grid size-12 place-items-center rounded-full bg-brand-50 text-brand-500"><Icon :name="icon" :size="24" /></span>
    <p class="mt-3 text-sm font-semibold text-slate-800">{{ title }}</p>
    <p v-if="text" class="mt-1 max-w-md text-sm text-slate-500">{{ text }}</p>
    <div class="mt-4"><slot /></div>
  </div>
</template>
