<script setup lang="ts">
import { STATUT, STATUT_BADGE } from '@/services/api'
/** `calm` : version sobre (bleu = en travail, gris = le reste) pour le tableau de bord. */
const props = defineProps<{ statut: string; calm?: boolean }>()
const CALM: Record<string, string> = { ouvert: 'badge-blue', en_cours: 'badge-blue' }
const cls = () => (props.calm ? (CALM[props.statut] ?? 'badge-slate') : (STATUT_BADGE[props.statut] ?? 'badge-slate'))
</script>
<template><span :class="cls()">{{ STATUT[statut] ?? statut }}</span></template>
