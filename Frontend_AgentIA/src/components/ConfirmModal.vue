<script setup lang="ts">
import { onBeforeUnmount, watch } from 'vue'
const props = defineProps<{ open: boolean; title: string; confirmLabel?: string; busy?: boolean }>()
const emit = defineEmits<{ confirm: []; cancel: [] }>()
const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') emit('cancel') }
watch(() => props.open, (v) => (v ? window.addEventListener('keydown', onKey) : window.removeEventListener('keydown', onKey)), { immediate: true })
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>
<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="open" class="fixed inset-0 z-50 grid place-items-center bg-slate-900/55 p-4 backdrop-blur-sm" role="dialog" aria-modal="true"
        @click.self="$emit('cancel')">
        <div class="w-full max-w-md rounded-2xl bg-white p-6 shadow-pop">
          <h2 class="text-base font-semibold text-slate-900">{{ title }}</h2>
          <div class="mt-2 text-sm text-slate-600"><slot /></div>
          <div class="mt-6 flex justify-end gap-2">
            <button class="btn-secondary" :disabled="busy" @click="$emit('cancel')">Annuler</button>
            <button class="btn-primary" :disabled="busy" @click="$emit('confirm')">{{ busy ? 'Traitement…' : (confirmLabel ?? 'Confirmer') }}</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
