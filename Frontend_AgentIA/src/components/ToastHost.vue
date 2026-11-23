<script setup lang="ts">
import { useToastStore } from '@/stores/toast'
import Icon from '@/components/Icon.vue'
const toast = useToastStore()
const TONE = { ok: 'border-emerald-200 bg-emerald-50 text-emerald-800', err: 'border-red-200 bg-red-50 text-red-800',
  info: 'border-slate-200 bg-white text-slate-800' }
</script>
<template>
  <div class="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-full max-w-sm flex-col gap-2" aria-live="polite">
    <TransitionGroup name="fade">
      <div v-for="t in toast.items" :key="t.id" class="pointer-events-auto flex items-start gap-2 rounded-xl border p-3 text-sm shadow-pop"
        :class="TONE[t.kind]" :role="t.kind === 'err' ? 'alert' : 'status'">
        <Icon :name="t.kind === 'ok' ? 'check' : t.kind === 'err' ? 'alert' : 'info'" :size="16" class="mt-0.5" />
        <p class="flex-1">{{ t.text }}</p>
        <button class="opacity-60 hover:opacity-100" aria-label="Fermer" @click="toast.dismiss(t.id)"><Icon name="x" :size="14" /></button>
      </div>
    </TransitionGroup>
  </div>
</template>
