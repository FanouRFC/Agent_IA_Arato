<script setup lang="ts">
import Icon from '@/components/Icon.vue'
/** Carte de chiffre clé : neutre (ciel), accent (bleu), attention (violet) ou alerte (corail, réservée aux retards). */
withDefaults(defineProps<{ label: string; value: number | string; icon: string; tone?: 'neutral' | 'accent' | 'violet' | 'alert'; hint?: string }>(),
  { tone: 'neutral' })
const ICON = { neutral: 'bg-slate-100 text-slate-600', accent: 'bg-slate-100 text-slate-600', violet: 'bg-slate-100 text-slate-600', alert: 'bg-red-50 text-red-600' }
const VALUE = { neutral: 'text-slate-900', accent: 'text-slate-900', violet: 'text-slate-900', alert: 'text-red-600' }
</script>
<template>
  <div class="card rise flex items-center gap-4 p-5 transition hover:-translate-y-0.5 hover:shadow-pop">
    <span class="grid size-12 shrink-0 place-items-center rounded-2xl" :class="ICON[tone]"><Icon :name="icon" :size="21" /></span>
    <div class="min-w-0">
      <p class="display text-3xl leading-none tabular-nums" :class="VALUE[tone]">{{ value }}</p>
      <p class="mt-1.5 truncate text-xs font-medium text-slate-500">{{ label }}</p>
      <p v-if="hint" class="truncate text-xs text-slate-400">{{ hint }}</p>
    </div>
  </div>
</template>
