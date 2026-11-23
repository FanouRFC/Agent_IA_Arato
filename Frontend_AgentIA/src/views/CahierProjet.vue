<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api, photoCrm, fmtDateTime } from '@/services/api'
import { useProjectStore } from '@/stores/project'
import Avatar from '@/components/Avatar.vue'
import EmptyState from '@/components/EmptyState.vue'
import Icon from '@/components/Icon.vue'
import PageHeader from '@/components/PageHeader.vue'

/* Cahier des charges VALIDÉ du projet en cours : tâches, durées, affectations (une ou plusieurs personnes) et
   dépendances établies par l'agent. Consultation seule : les modifications se font avant la validation. */
const project = useProjectStore()
const d = ref<any>(null), err = ref(''), vue = ref<'liste' | 'dependances'>('liste')
async function load() {
  if (!project.activeId) return
  try { d.value = await api(`/projets/${project.activeId}/cahier`); err.value = '' } catch (e: any) { err.value = e.message }
}
watch(() => project.activeId, () => { d.value = null; load() }, { immediate: true })

const cahier = computed(() => d.value?.cahier)
const taches = computed<any[]>(() => cahier.value?.taches ?? [])
const roster = computed<Record<number, any>>(() => Object.fromEntries((d.value?.membres ?? []).map((m: any) => [m.id, m])))
const titreDe = (ordre: number) => taches.value.find((t) => t.ordre === ordre)?.titre ?? `Tâche ${ordre}`
const equipe = computed(() => [...new Set(taches.value.flatMap((t) => t.membre_ids || []))].map((i) => roster.value[i as number]).filter(Boolean))
const nbDeps = computed(() => taches.value.reduce((s, t) => s + (t.depend_de?.length || 0), 0))
const totalJours = computed(() => taches.value.reduce((s, t) => s + (t.duree_estimee || 0), 0))
const PRIO: Record<string, string> = { haute: 'Haute', moyenne: 'Moyenne', basse: 'Basse' }

/** Niveaux de la carte des dépendances : une tâche est placée une colonne après son préalable le plus tardif. */
const niveaux = computed(() => {
  const niv = new Map<number, number>()
  const par = new Map<number, any>(taches.value.map((t) => [t.ordre, t]))
  const rang = (o: number, vus: Set<number> = new Set()): number => {
    if (niv.has(o)) return niv.get(o)!
    if (vus.has(o)) return 0
    vus.add(o)
    const deps: number[] = (par.get(o)?.depend_de ?? []).filter((x: number) => par.has(x))
    const n = deps.length ? 1 + Math.max(...deps.map((x) => rang(x, vus))) : 0
    niv.set(o, n)
    return n
  }
  taches.value.forEach((t) => rang(t.ordre))
  const cols: any[][] = []
  taches.value.forEach((t) => { const n = niv.get(t.ordre) ?? 0; (cols[n] ??= []).push(t) })
  return cols.filter(Boolean)
})
const bloquees = (ordre: number) => taches.value.filter((t) => (t.depend_de || []).includes(ordre))
</script>

<template>
  <PageHeader title="Cahier des charges du projet" :subtitle="cahier ? `« ${cahier.nom_projet} » · déposé le ${fmtDateTime(cahier.date_depot)}` : (project.active ? `Projet « ${project.active.nom} »` : '')">
    <div v-if="cahier" class="inline-flex rounded-xl border border-line bg-white p-1 text-xs font-medium" role="tablist" aria-label="Affichage">
      <button v-for="m in (['liste', 'dependances'] as const)" :key="m" role="tab" :aria-selected="vue === m" type="button"
        class="rounded-lg px-3 py-1.5 transition" :class="vue === m ? 'bg-slate-900 text-white' : 'text-slate-500 hover:text-slate-900'" @click="vue = m">
        {{ m === 'liste' ? 'Tâches' : 'Dépendances' }}</button>
    </div>
  </PageHeader>

  <p v-if="err" class="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">{{ err }}</p>
  <div v-else-if="!d" class="card card-pad flex items-center gap-3" role="status"><Icon name="refresh" :size="18" class="animate-spin text-brand-600" /><p class="muted">Chargement du cahier des charges…</p></div>
  <div v-else-if="!cahier" class="card"><EmptyState icon="file" title="Pas de cahier des charges pour ce projet" text="Ce projet a été créé directement dans le CRM : aucun cahier n'a été validé dans l'application." /></div>

  <template v-else>
    <!-- Chiffres -->
    <section class="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <div v-for="k in [
        { v: taches.length, l: 'tâches', i: 'list' }, { v: totalJours, l: 'jours estimés au total', i: 'clock' },
        { v: equipe.length, l: 'membres mobilisés', i: 'users' }, { v: nbDeps, l: 'dépendances entre tâches', i: 'network' }]" :key="k.l"
        class="card flex items-center gap-4 p-5"><span class="grid size-11 place-items-center rounded-xl bg-slate-100 text-slate-600"><Icon :name="k.i" :size="19" /></span>
        <div><p class="display text-2xl leading-none tabular-nums text-slate-900">{{ k.v }}</p><p class="mt-1 text-xs text-slate-500">{{ k.l }}</p></div></div>
    </section>

    <!-- Équipe du projet : union des membres affectés aux tâches -->
    <section v-if="equipe.length" class="card mb-6 flex flex-wrap items-center gap-4 px-5 py-4">
      <p class="eyebrow">Équipe du projet</p>
      <ul class="flex flex-wrap gap-2"><li v-for="m in equipe" :key="m.id" class="inline-flex items-center gap-2 rounded-full border border-line bg-white py-1 pl-1 pr-3 text-xs text-slate-700">
        <Avatar :nom="m.nom" :src="photoCrm(m.photo)" :size="22" /><span class="font-medium">{{ m.nom }}</span><span class="text-slate-400">{{ m.profil }}</span></li></ul>
    </section>

    <!-- Liste des tâches -->
    <section v-if="vue === 'liste'" class="space-y-3">
      <article v-for="t in taches" :key="t.id" class="card p-5">
        <div class="flex flex-wrap items-start gap-3">
          <span class="grid size-8 shrink-0 place-items-center rounded-lg bg-slate-900 text-xs font-semibold text-white">{{ t.ordre }}</span>
          <div class="min-w-0 flex-1">
            <h3 class="text-[15px] font-semibold leading-snug text-slate-900">{{ t.titre }}</h3>
            <p v-if="t.description" class="mt-1 text-sm leading-relaxed text-slate-600">{{ t.description }}</p>
            <div v-if="(t.criteres_acceptation || []).length" class="mt-3">
              <p class="eyebrow">Critères d'acceptation</p>
              <ol class="mt-1.5 list-decimal space-y-1 pl-5 text-sm text-slate-600"><li v-for="c in t.criteres_acceptation" :key="c">{{ c }}</li></ol>
            </div>
          </div>
          <div class="flex shrink-0 flex-wrap items-center gap-2 text-xs">
            <span class="badge-slate">{{ PRIO[t.priorite] ?? t.priorite }}</span><span class="badge-slate">{{ t.duree_estimee }} j</span>
            <RouterLink v-if="t.id_ticket_crm" :to="`/tickets/${t.id_ticket_crm}`" class="badge-blue hover:underline">T-{{ String(t.id_ticket_crm).padStart(3, '0') }}</RouterLink>
          </div>
        </div>
        <div class="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-line pt-3 text-xs text-slate-500">
          <span class="inline-flex items-center gap-2"><Icon name="users" :size="13" />
            <template v-if="(t.membre_ids || []).length"><span class="flex -space-x-2"><Avatar v-for="i in t.membre_ids" :key="i" :nom="roster[i]?.nom ?? '?'" :src="photoCrm(roster[i]?.photo)" :size="24" ring /></span>
              <span>{{ t.membre_ids.length > 1 ? 'Affectée à ' + t.membre_ids.length + ' personnes' : 'Affectée à ' + (roster[t.membre_ids[0]]?.nom ?? '?') }}</span></template>
            <span v-else>Non affectée</span></span>
          <span v-if="t.depend_de?.length" class="inline-flex flex-wrap items-center gap-1.5"><Icon name="link" :size="13" />Dépend de
            <span v-for="x in t.depend_de" :key="x" class="badge-slate max-w-56 truncate">{{ titreDe(x) }}</span></span>
          <span v-else class="inline-flex items-center gap-1.5"><Icon name="link" :size="13" />Aucune dépendance</span>
        </div>
      </article>
    </section>

    <!-- Carte des dépendances : colonnes = ordre d'exécution -->
    <section v-else class="card overflow-x-auto p-6">
      <p class="mb-5 text-sm text-slate-500">Lecture de gauche à droite : une tâche ne démarre qu'une fois ses préalables terminés. {{ nbDeps ? '' : 'Aucune dépendance n\'a été établie pour ce projet.' }}</p>
      <div class="flex min-w-max items-stretch gap-10">
        <div v-for="(col, n) in niveaux" :key="n" class="flex w-64 shrink-0 flex-col gap-3">
          <p class="eyebrow">{{ n === 0 ? 'Départ' : 'Étape ' + (n + 1) }}</p>
          <div v-for="t in col" :key="t.id" class="rounded-xl border border-line bg-slate-50/70 p-3.5">
            <p class="text-sm font-semibold leading-snug text-slate-900">{{ t.titre }}</p>
            <p class="mt-1 text-xs text-slate-500">{{ t.duree_estimee }} j · {{ (t.membre_ids || []).length || 'aucun' }} membre(s)</p>
            <p v-if="t.depend_de?.length" class="mt-2 text-xs text-slate-500">← après : {{ t.depend_de.map(titreDe).join(' ; ') }}</p>
            <p v-if="bloquees(t.ordre).length" class="mt-1 text-xs text-brand-700">→ débloque : {{ bloquees(t.ordre).map((x: any) => x.titre).join(' ; ') }}</p>
          </div>
        </div>
      </div>
    </section>
  </template>
</template>
