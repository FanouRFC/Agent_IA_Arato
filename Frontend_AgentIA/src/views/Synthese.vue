<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { api, download, fmtDateTime, tid } from '@/services/api'

const s = ref<any>(null), err = ref('')
let timer: number
async function load() {
  try { s.value = await api('/synthese') } catch (e: any) { err.value = e.message }
}
async function decide(id: number, decision: 'suivie' | 'rejetee') {
  await api(`/recommandations/${id}/decision`, { method: 'POST', body: JSON.stringify({ decision }) })
  await load()
}
const refresh = async () => { await api('/synthese/actualiser', { method: 'POST' }); setTimeout(load, 1500) }
// La synthèse se met à jour côté serveur à chaque événement ; l'interface l'interroge régulièrement.
onMounted(() => { load(); timer = window.setInterval(load, 8000) })
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="flex flex-wrap items-center gap-3">
    <h1 class="text-2xl font-semibold">Situation du projet</h1>
    <div class="ml-auto flex gap-2">
      <button class="btn-quiet" @click="refresh">Réévaluer maintenant</button>
      <button class="btn-quiet" @click="download('/rapports/pdf', 'rapport_suivi.pdf')">Rapport PDF</button>
      <button class="btn-quiet" @click="download('/rapports/xlsx', 'rapport_suivi.xlsx')">Rapport Excel</button>
    </div>
  </div>
  <p v-if="err" class="mt-4 text-brick" role="alert">{{ err }}</p>
  <p v-else-if="!s" class="mt-6 text-ink/70">Aucune analyse pour l'instant. Elle apparaît dès le premier événement du CRM ou du calendrier.</p>
  <template v-else>
    <div class="mt-5 grid gap-3 sm:grid-cols-3">
      <div class="panel border-l-4 border-l-brick"><p class="text-3xl font-semibold">{{ s.nb_en_retard }}</p><p class="text-sm">en retard</p></div>
      <div class="panel border-l-4 border-l-ochre"><p class="text-3xl font-semibold">{{ s.nb_a_surveiller }}</p><p class="text-sm">à surveiller</p></div>
      <div class="panel border-l-4 border-l-teal"><p class="text-3xl font-semibold">{{ s.nb_en_attente }}</p><p class="text-sm">en attente</p></div>
    </div>
    <section class="panel mt-4">
      <p class="text-xs text-ink/60">Actualisée le {{ fmtDateTime(s.date) }} · déclencheur : {{ s.declencheur }}</p>
      <p class="mt-2 max-w-3xl leading-relaxed">{{ s.contenu }}</p>
      <ul v-if="s.evolutions.length" class="mt-3 list-disc pl-5 text-sm">
        <li v-for="e in s.evolutions" :key="e">{{ e }}</li>
      </ul>
    </section>
    <section class="mt-6">
      <h2 class="text-lg font-semibold">Recommandations à examiner</h2>
      <p v-if="!s.recommandations.length" class="mt-2 text-ink/70">Aucune recommandation en attente de décision.</p>
      <div v-for="r in s.recommandations" :key="r.id" class="panel mt-3 flex flex-wrap items-center gap-3">
        <p class="max-w-3xl flex-1">{{ r.texte }}</p>
        <button class="btn" @click="decide(r.id, 'suivie')">Suivre</button>
        <button class="btn-quiet" @click="decide(r.id, 'rejetee')">Rejeter</button>
      </div>
    </section>
  </template>
</template>
