<script setup lang="ts">
defineProps<{ title: string; subtitle?: string }>()
</script>
<template>
  <div class="mb-6 flex flex-wrap items-end gap-3">
    <div class="min-w-0 flex-1">
      <h1 class="text-xl font-semibold tracking-tight text-slate-900 sm:text-2xl">{{ title }}</h1>
      <p v-if="subtitle" class="mt-1 text-sm text-slate-500">{{ subtitle }}</p>
    </div>
    <div class="flex flex-wrap items-center gap-2"><slot /></div>
  </div>
</template>
