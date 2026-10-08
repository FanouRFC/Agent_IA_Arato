<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '@/services/api'

const projets = ref<any[]>([]), membres = ref<any[]>([])
const nom = ref(''), projetId = ref<number | null>(null), texte = ref(''), fichier = ref<File | null>(null)
const cahier = ref<any>(null), busy = ref(false), err = ref(''), bilan = ref<any>(null)
const PRIORITES = ['haute', 'moyenne', 'basse']

onMounted(async () => {
  try { [projets.value, membres.value] = await Promise.all([api('/crm/projets'), api('/crm/membres')]) }
  catch (e: any) { err.value = e.message }
})

async function analyser() {
  err.value = ''; busy.value = true
  const f = new FormData()
  f.append('projet_nom', nom.value); f.append('crm_projet_id', String(projetId.value)); f.append('texte', texte.value)
  if (fichier.value) f.append('fichier', fichier.value)
  try { cahier.value = await api('/cahiers', { method: 'POST', body: f }) } catch (e: any) { err.value = e.message }
  busy.value = false
}
const save = (t: any) => api(`/taches/${t.id}`, { method: 'PUT', body: JSON.stringify({
  titre: t.titre, description: t.description, priorite: t.priorite, duree_estimee: t.duree_estimee, membre_ids: t.membre_ids }) })
  .catch((e: any) => (err.value = e.message))
async function remove(t: any) {
  await api(`/taches/${t.id}`, { method: 'DELETE' }); cahier.value.taches = cahier.value.taches.filter((x: any) => x.id !== t.id)
}
async function ajouter() {
  const t = await api(`/cahiers/${cahier.value.id}/taches`, { method: 'POST', body: JSON.stringify({ titre: 'Nouvelle tâche', duree_estimee: 1 }) })
  cahier.value.taches.push(t)
}
async function valider() {
  err.value = ''; busy.value = true
  try { bilan.value = await api(`/cahiers/${cahier.value.id}/valider`, { method: 'POST' }) } catch (e: any) { err.value = e.message }
  busy.value = false
}
</script>

<template>
  <h1 class="text-2xl font-semibold">Cahier des charges</h1>
  <p v-if="err" class="mt-3 text-brick" role="alert">{{ err }}</p>

  <section v-if="bilan" class="panel mt-4">
    <h2 class="font-semibold">Bilan de création</h2>
    <p class="mt-2">{{ bilan.tickets_crees }} ticket(s) créé(s) dans le CRM ; les membres affectés ont été notifiés par e-mail.</p>
    <ul v-if="bilan.erreurs.length" class="mt-2 list-disc pl-5 text-sm text-brick"><li v-for="e in bilan.erreurs" :key="e">{{ e }}</li></ul>
  </section>

  <section v-else-if="!cahier" class="panel mt-4 space-y-3">
    <p class="text-sm text-ink/70">Saisissez le cahier des charges présenté par le chef de projet : PDF, Word ou texte. Aucun ticket n'est créé avant votre validation.</p>
    <div class="grid gap-3 sm:grid-cols-2">
      <label class="text-sm">Nom du projet<input v-model="nom" class="field mt-1" /></label>
      <label class="text-sm">Projet du CRM
        <select v-model="projetId" class="field mt-1"><option :value="null" disabled>Choisir…</option>
          <option v-for="p in projets" :key="p.id" :value="p.id">{{ p.nom }}</option></select></label>
    </div>
    <label class="block text-sm">Fichier (.pdf, .docx, .txt)
      <input type="file" accept=".pdf,.docx,.txt,.md" class="field mt-1" @change="fichier = ($event.target as HTMLInputElement).files?.[0] ?? null" /></label>
    <label class="block text-sm">…ou texte<textarea v-model="texte" rows="6" class="field mt-1"></textarea></label>
    <button class="btn" :disabled="busy || !nom || !projetId || (!fichier && texte.length < 30)" @click="analyser">
      {{ busy ? 'Analyse en cours…' : 'Analyser le document' }}</button>
  </section>

  <template v-else>
    <div v-if="cahier.ambiguites.length" class="panel mt-4 border-l-4 border-l-ochre">
      <h2 class="font-semibold">Ambiguïtés et informations manquantes</h2>
      <ul class="mt-1 list-disc pl-5 text-sm"><li v-for="a in cahier.ambiguites" :key="a">{{ a }}</li></ul>
    </div>
    <p class="mt-4 text-sm text-ink/70">Relisez le brouillon : modifiez, supprimez ou ajoutez des tâches (durées en jours ouvrés), puis validez.</p>
    <div v-for="t in cahier.taches" :key="t.id" class="panel mt-3">
      <div class="flex flex-wrap items-center gap-2">
        <input v-model="t.titre" class="field flex-1 font-medium!" @change="save(t)" aria-label="Titre" />
        <select v-model="t.priorite" class="field w-28!" @change="save(t)" aria-label="Priorité">
          <option v-for="p in PRIORITES" :key="p">{{ p }}</option></select>
        <label class="flex items-center gap-1 text-sm">Durée
          <input v-model.number="t.duree_estimee" type="number" min="1" class="field w-16!" @change="save(t)" /> j</label>
        <button class="btn-quiet" @click="remove(t)">Supprimer</button>
      </div>
      <textarea v-model="t.description" rows="2" class="field mt-2" @change="save(t)" aria-label="Description"></textarea>
      <p class="mt-2 text-xs text-ink/70">Priorité : {{ t.raison_priorite || '—' }} · confiance {{ Math.round(t.niveau_confiance * 100) }} %
        · profil recommandé : {{ t.profil_recommande || '—' }}
        <span v-if="t.depend_de.length"> · dépend de : {{ t.depend_de.join(', ') }}</span></p>
      <p v-if="t.source_dans_document" class="mt-1 text-xs italic text-ink/60">Source : « {{ t.source_dans_document }} »</p>
      <p v-for="a in t.ambiguites" :key="a" class="mt-1 text-xs text-ochre">{{ a }}</p>
      <label class="mt-2 block text-sm">Affectation (un ou plusieurs membres)
        <select v-model="t.membre_ids" multiple class="field mt-1 h-24" @change="save(t)">
          <option v-for="m in membres" :key="m.id" :value="m.id">{{ m.nom }} — {{ m.profil }}</option></select></label>
    </div>
    <div class="mt-4 flex gap-2">
      <button class="btn-quiet" @click="ajouter">Ajouter une tâche</button>
      <button class="btn" :disabled="busy || !cahier.taches.length" @click="valider">
        {{ busy ? 'Création…' : 'Valider et créer les tickets' }}</button>
    </div>
  </template>
</template>
