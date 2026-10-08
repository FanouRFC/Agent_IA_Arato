<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, fmtDateTime } from '@/services/api'

const s = ref<any>({ seuil_jours: 2, seuil_avancement: 50, jours_feries: [], llm_model: '' })
const feries = ref(''), journal = ref<any[]>([]), ev = ref<any>(null), msg = ref(''), err = ref('')
async function load() {
  s.value = await api('/admin/settings'); feries.value = s.value.jours_feries.join('\n')
  journal.value = await api('/admin/journal'); ev.value = await api('/evaluation')
}
async function save() {
  err.value = msg.value = ''
  try {
    await api('/admin/settings', { method: 'PUT', body: JSON.stringify({
      ...s.value, jours_feries: feries.value.split(/\s+/).filter(Boolean) }) })
    msg.value = 'Paramètres enregistrés.'; journal.value = await api('/admin/journal')
  } catch (e: any) { err.value = e.message }
}
const pct = (x: number) => `${Math.round(x * 100)} %`
onMounted(load)
</script>

<template>
  <h1 class="text-2xl font-semibold">Administration</h1>
  <section class="panel mt-4">
    <h2 class="font-semibold">Détection des situations à surveiller</h2>
    <p class="text-sm text-ink/70">Une tâche est « à surveiller » si son échéance est dans X jours ouvrés au plus et son avancement déclaré ≤ Y %.</p>
    <div class="mt-3 grid gap-3 sm:grid-cols-3">
      <label class="text-sm">X (jours ouvrés)<input v-model.number="s.seuil_jours" type="number" min="0" class="field mt-1" /></label>
      <label class="text-sm">Y (avancement, %)<input v-model.number="s.seuil_avancement" type="number" min="0" max="100" class="field mt-1" /></label>
      <label class="text-sm">Modèle d'IA<input v-model="s.llm_model" class="field mt-1" /></label>
    </div>
    <label class="mt-3 block text-sm">Jours fériés (un par ligne, AAAA-MM-JJ)
      <textarea v-model="feries" rows="4" class="field mt-1 font-mono"></textarea></label>
    <button class="btn mt-3" @click="save">Enregistrer</button>
    <span v-if="msg" class="ml-3 text-sm text-teal">{{ msg }}</span><span v-if="err" class="ml-3 text-sm text-brick" role="alert">{{ err }}</span>
  </section>
  <section v-if="ev" class="panel mt-4">
    <h2 class="font-semibold">Évaluation de l'agent</h2>
    <div class="mt-2 grid gap-4 text-sm sm:grid-cols-2">
      <ul class="space-y-1"><li><b>Création des tâches</b> ({{ ev.taches.proposees }} proposées)</li>
        <li>Acceptation directe : {{ pct(ev.taches.taux_acceptation_directe) }}</li>
        <li>Correction humaine : {{ pct(ev.taches.taux_correction) }}</li><li>Rejet : {{ pct(ev.taches.taux_rejet) }}</li>
        <li>Écart de durée moyen : {{ ev.taches.ecart_duree_moyen.toFixed(1) }} jour(s)</li></ul>
      <ul class="space-y-1"><li><b>Recommandations</b> ({{ ev.recommandations.emises }} émises)</li>
        <li>Taux de suivi : {{ pct(ev.recommandations.taux_suivi) }}</li><li>Taux de rejet : {{ pct(ev.recommandations.taux_rejet) }}</li>
        <li>Contenant « relance » : {{ ev.recommandations.contenant_relance }}</li>
        <li>Repli déterministe : {{ ev.recommandations.repli_deterministe }}</li></ul>
    </div>
  </section>
  <section class="panel mt-4">
    <h2 class="font-semibold">Journal des actions</h2>
    <ul class="mt-2 max-h-72 space-y-1 overflow-y-auto text-sm">
      <li v-for="(j, i) in journal" :key="i"><span class="text-ink/60">{{ fmtDateTime(j.date) }} · {{ j.auteur }}</span> — {{ j.action }}</li>
    </ul>
  </section>
</template>
