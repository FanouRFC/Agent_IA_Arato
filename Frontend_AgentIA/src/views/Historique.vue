<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api, fmtDateTime, ilYa } from '@/services/api'
import { usePolling } from '@/composables/usePolling'
import { useProjectStore } from '@/stores/project'
import EmptyState from '@/components/EmptyState.vue'
import Icon from '@/components/Icon.vue'
import PageHeader from '@/components/PageHeader.vue'

/* Historique : journal de bord de CE projet uniquement (actions, évolutions constatées par l'agent, décisions sur les
   recommandations, rapports). Le journal général de toute l'application se trouve dans Administration → Journal. */
const project = useProjectStore()
const entrees = ref<any[]>([]), err = ref(''), charge = ref(false)
const jour = ref(''), sept = ref(false), type = ref<'tous' | 'action' | 'evolution' | 'recommandation' | 'rapport'>('tous')
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const jourMoins = (n: number) => { const d = new Date(); d.setDate(d.getDate() - n); return iso(d) }

async function load() {
  if (!project.activeId) return
  const qs = new URLSearchParams()
  if (sept.value) { qs.set('du', jourMoins(6)); qs.set('au', iso(new Date())) }
  else if (jour.value) { qs.set('du', jour.value); qs.set('au', jour.value) }
  try { entrees.value = (await api(`/projets/${project.activeId}/historique?${qs}`)).entrees; err.value = '' }
  catch (e: any) { err.value = e.message }
  charge.value = true
}
usePolling(load, 5000)
watch(() => project.activeId, () => { entrees.value = []; charge.value = false; load() })
watch([jour, sept], load)
watch(jour, (v) => { if (v) sept.value = false })
const choisirSept = () => { sept.value = !sept.value; if (sept.value) jour.value = '' }
const reinitialiser = () => { jour.value = ''; sept.value = false }

const TYPES = [
  { k: 'tous', l: 'Tout', i: 'list' }, { k: 'action', l: 'Actions', i: 'user' }, { k: 'evolution', l: 'Évolutions', i: 'trending' },
  { k: 'recommandation', l: 'Recommandations', i: 'sparkles' }, { k: 'rapport', l: 'Rapports', i: 'download' },
] as const
const ICONE: Record<string, string> = { action: 'user', evolution: 'trending', recommandation: 'sparkles', rapport: 'download' }
const nb = (k: string) => (k === 'tous' ? entrees.value.length : entrees.value.filter((e) => e.type === k).length)
const visibles = computed(() => entrees.value.filter((e) => type.value === 'tous' || e.type === type.value))

/** Regroupement par jour, du plus récent au plus ancien. */
const groupes = computed(() => {
  const m = new Map<string, any[]>()
  for (const e of visibles.value) {
    const k = new Date(e.date).toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
    ;(m.get(k) ?? m.set(k, []).get(k)!).push(e)
  }
  return [...m.entries()].map(([jourLib, items]) => ({ jourLib, items }))
})
const heure = (d: string) => new Date(d).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
/** Les numéros de tâche (T-014) deviennent des liens vers l'analyse de la tâche. */
function morceaux(txt: string): { t: string; id?: number }[] {
  return txt.split(/(T-0*\d+)/g).filter(Boolean).map((t) => { const m = t.match(/^T-0*(\d+)$/); return m ? { t, id: Number(m[1]) } : { t } })
}
</script>

<template>
  <PageHeader title="Historique du projet" :subtitle="project.active ? `Journal de bord de « ${project.active.nom} » uniquement` : ''">
    <RouterLink to="/admin" class="btn-ghost btn-sm" title="Journal général de toute l'application"><Icon name="layers" :size="14" /> Journal général</RouterLink>
  </PageHeader>

  <!-- Filtres -->
  <section class="card mb-5 flex flex-wrap items-center gap-3 px-4 py-3">
    <div class="inline-flex flex-wrap rounded-xl bg-slate-100 p-1" role="tablist" aria-label="Type d'entrée">
      <button v-for="t in TYPES" :key="t.k" role="tab" :aria-selected="type === t.k" type="button"
        class="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition"
        :class="type === t.k ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-700 hover:text-slate-900'" @click="type = t.k">
        <Icon :name="t.i" :size="13" />{{ t.l }}<span class="text-xs tabular-nums opacity-80">{{ nb(t.k) }}</span></button>
    </div>
    <div class="ml-auto flex flex-wrap items-center gap-2">
      <label class="sr-only" for="h-jour">Date précise</label>
      <input id="h-jour" v-model="jour" type="date" class="input w-auto!" :max="iso(new Date())" />
      <button type="button" class="btn-sm rounded-xl border px-3 py-1.5 text-sm font-medium transition"
        :class="sept ? 'border-slate-900 bg-slate-900 text-white' : 'border-slate-300 bg-white text-slate-700 hover:border-brand-300'" @click="choisirSept">7 derniers jours</button>
      <button v-if="jour || sept" type="button" class="btn-ghost btn-sm" @click="reinitialiser"><Icon name="x" :size="13" /> Tout afficher</button>
    </div>
  </section>

  <p v-if="err" class="mb-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">{{ err }}</p>

  <div v-if="!charge" class="card card-pad flex items-center gap-3" role="status"><Icon name="refresh" :size="18" class="animate-spin text-brand-600" /><p class="muted">Chargement de l'historique…</p></div>
  <div v-else-if="!visibles.length" class="card"><EmptyState icon="history" title="Aucune entrée" text="Rien n'a été enregistré pour ce projet sur cette période. Les changements du CRM, les décisions et les rapports apparaîtront ici." /></div>

  <!-- Chronologie par jour -->
  <div v-else class="space-y-8">
    <section v-for="g in groupes" :key="g.jourLib" :aria-label="g.jourLib">
      <h2 class="mb-3 flex items-center gap-3 text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">
        <span>{{ g.jourLib }}</span><span class="h-px flex-1 bg-line" /><span class="tabular-nums text-slate-500">{{ g.items.length }}</span></h2>
      <ol class="card divide-y divide-line">
        <li v-for="(e, i) in g.items" :key="e.date + i" class="flex items-start gap-4 px-5 py-3.5">
          <span class="mt-0.5 grid size-8 shrink-0 place-items-center rounded-xl bg-slate-100 text-slate-600"><Icon :name="ICONE[e.type] ?? 'info'" :size="15" /></span>
          <div class="min-w-0 flex-1">
            <p class="break-anywhere text-sm leading-relaxed text-slate-900">
              <template v-for="(m, k) in morceaux(e.texte)" :key="k"><RouterLink v-if="m.id" :to="`/tickets/${m.id}`" class="font-semibold text-brand-700 hover:underline">{{ m.t }}</RouterLink><template v-else>{{ m.t }}</template></template>
            </p>
            <p class="mt-0.5 text-xs text-slate-500">{{ heure(e.date) }} · {{ e.auteur }}<span class="hidden sm:inline"> · {{ ilYa(e.date) }}</span></p>
          </div>
          <span class="hidden shrink-0 text-xs tabular-nums text-slate-500 md:block" :title="fmtDateTime(e.date)">{{ fmtDateTime(e.date) }}</span>
        </li>
      </ol>
    </section>
  </div>
</template>
