<script setup lang="ts">
import { onBeforeUnmount, watch } from 'vue'
import Icon from '@/components/Icon.vue'

/** Fenêtre contextuelle générique : fond flouté, fermeture par Échap / clic extérieur / bouton, défilement interne. */
const props = withDefaults(defineProps<{ open: boolean; title?: string; subtitle?: string; size?: 'md' | 'lg' | 'xl' }>(), { size: 'lg' })
const emit = defineEmits<{ close: [] }>()
const WIDTH = { md: 'max-w-lg', lg: 'max-w-2xl', xl: 'max-w-4xl' }

// Une confirmation (role="dialog") ouverte par-dessus garde la main sur la touche Échap.
function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && document.querySelectorAll('[role="dialog"]').length <= 1) emit('close')
}
watch(() => props.open, (v) => {
  document.body.style.overflow = v ? 'hidden' : ''
  if (v) window.addEventListener('keydown', onKey)
  else window.removeEventListener('keydown', onKey)
}, { immediate: true })
onBeforeUnmount(() => { document.body.style.overflow = ''; window.removeEventListener('keydown', onKey) })
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="open" class="fixed inset-0 z-40 flex items-end justify-center bg-slate-900/55 p-0 backdrop-blur-sm sm:items-center sm:p-6"
        role="dialog" aria-modal="true" :aria-label="title" @click.self="emit('close')">
        <div class="modal-panel flex max-h-[92vh] w-full flex-col overflow-hidden rounded-t-2xl bg-white shadow-pop sm:rounded-2xl" :class="WIDTH[size]">
          <header class="flex items-start gap-3 border-b border-line px-6 py-4">
            <div class="min-w-0 flex-1">
              <slot name="header"><h2 class="text-base font-semibold text-slate-900">{{ title }}</h2>
                <p v-if="subtitle" class="mt-0.5 text-sm text-slate-500">{{ subtitle }}</p></slot>
            </div>
            <slot name="actions" />
            <button class="btn-ghost -mr-2 -mt-1 size-8 !p-0" aria-label="Fermer" @click="emit('close')"><Icon name="x" :size="18" /></button>
          </header>
          <div class="min-h-0 flex-1 overflow-y-auto px-6 py-5"><slot /></div>
          <footer v-if="$slots.footer" class="flex flex-wrap items-center justify-end gap-2 border-t border-line bg-slate-50/70 px-6 py-3"><slot name="footer" /></footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
