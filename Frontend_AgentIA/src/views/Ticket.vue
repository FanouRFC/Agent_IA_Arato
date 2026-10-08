<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, fmtDate, fmtDateTime, SITUATION_CLASS, STATUT, tid } from '@/services/api'

const id = Number(useRoute().params.id)
const d = ref<any>(null), err = ref(''), msg = ref('')
const nouvelle = ref(''), motif = ref('')
async function load() { try { d.value = await api(`/tickets/${id}/analyse`) } catch (e: any) { err.value = e.message } }
async function decide(rid: number, decision: string) {
  await api(`/recommandations/${rid}/decision`, { method: 'POST', body: JSON.stringify({ decision }) }); await load()
}
async function changeEcheance() {
  err.value = msg.value = ''
  try {
    await api(`/tickets/${id}/echeance`, { method: 'PUT', body: JSON.stringify({ nouvelle_date: nouvelle.value, motif: motif.value }) })
    msg.value = 'Échéance modifiée et inscrite au journal.'; nouvelle.value = motif.value = ''
    setTimeout(load, 1500)
  } catch (e: any) { err.value = e.message }
}
onMounted(load)
</script>

<template>
  <router-link to="/tableau" class="text-sm text-teal underline">← Tableau de bord</router-link>
  <p v-if="err" class="mt-3 text-brick" role="alert">{{ err }}</p>
  <template v-if="d">
    <h1 class="mt-2 text-2xl font-semibold">{{ tid(id) }} · {{ d.ticket.titre }}</h1>
    <div class="mt-3 flex flex-wrap gap-2 text-sm">
      <span class="tag bg-line/60">{{ STATUT[d.ticket.statut] }}</span>
      <span class="tag bg-line/60">Avancement déclaré : {{ d.ticket.avancement_declare }} %</span>
      <span class="tag" :class="SITUATION_CLASS[d.calculs.situation]">{{ d.calculs.libelle }}</span>
      <span class="tag bg-line/60">Échéance : {{ fmtDate(d.ticket.echeance) }}</span>
      <span v-if="d.bloque.length" class="tag bg-ochre-soft text-ochre">Bloque : {{ d.bloque.map(tid).join(', ') }}</span>
    </div>
    <p class="mt-3 max-w-3xl text-sm">{{ d.ticket.description }}</p>
    <p class="mt-1 text-xs text-ink/60">Membres : {{ d.membres.map((m: any) => m.nom).join(', ') || '—' }}</p>

    <section class="panel mt-5">
      <h2 class="font-semibold">Analyse de l'agent</h2>
      <template v-if="d.analyse">
        <p class="mt-1 text-xs text-ink/60">{{ fmtDateTime(d.analyse_date) }} · risque {{ d.analyse.risque }}
          <span v-if="d.analyse.source === 'fallback'"> · analyse déterministe (modèle indisponible ou non conforme)</span></p>
        <p class="mt-2 max-w-3xl">{{ d.analyse.analyse }}</p>
        <p v-if="d.analyse.prediction" class="mt-2 max-w-3xl"><b>Prédiction.</b> {{ d.analyse.prediction }}</p>
      </template>
      <p v-else class="mt-2 text-ink/70">Pas encore d'analyse : elle est produite dès qu'un événement pertinent concerne ce ticket.</p>
      <div v-for="r in d.recommandations.slice(0, 1)" :key="r.id" class="mt-4 rounded-md bg-teal-soft p-3">
        <p>{{ r.texte }}</p>
        <div v-if="!r.decision" class="mt-2 flex gap-2">
          <button class="btn" @click="decide(r.id, 'suivie')">Suivre</button>
          <button class="btn-quiet" @click="decide(r.id, 'rejetee')">Rejeter</button>
        </div>
        <p v-else class="mt-1 text-xs">Décision : {{ r.decision === 'suivie' ? 'suivie' : 'rejetée' }}</p>
      </div>
    </section>

    <section class="panel mt-4">
      <h2 class="font-semibold">Historique des blocages et des avancements</h2>
      <ul class="mt-2 space-y-1 text-sm">
        <li v-for="(h, i) in d.historique.statuts" :key="i">
          <span class="text-ink/60">{{ fmtDate(h.date) }}</span> · {{ STATUT[h.statut] }}
          <template v-if="h.type_motif"> · <b>{{ h.type_motif === 'attente' ? 'Motif d\'attente' : 'Motif de retard' }}</b> : {{ h.motif }}
            <span v-if="h.date_resolution" class="text-ink/60"> (résolu le {{ fmtDate(h.date_resolution) }})</span></template>
        </li>
        <li v-for="(a, i) in d.historique.avancements" :key="'a' + i" class="text-ink/80">
          <span class="text-ink/60">{{ fmtDate(a.date) }}</span> · l'avancement déclaré est passé de {{ a.ancienne }} % à {{ a.nouvelle }} %</li>
      </ul>
    </section>

    <section class="panel mt-4">
      <h2 class="font-semibold">Modifier l'échéance</h2>
      <p class="text-sm text-ink/70">Décision du haut responsable, avec motif ; l'agent ne peut que la recommander.</p>
      <div class="mt-3 flex flex-wrap items-end gap-3">
        <label class="text-sm">Nouvelle date<input v-model="nouvelle" type="date" class="field mt-1" /></label>
        <label class="flex-1 text-sm">Motif<input v-model="motif" class="field mt-1" /></label>
        <button class="btn" :disabled="!nouvelle || motif.length < 3" @click="changeEcheance">Modifier l'échéance</button>
      </div>
      <p v-if="msg" class="mt-2 text-sm text-teal">{{ msg }}</p>
    </section>
  </template>
</template>
