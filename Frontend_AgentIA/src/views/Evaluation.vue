<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '@/services/api'
import { usePolling } from '@/composables/usePolling'
import { useProjectStore } from '@/stores/project'
import EmptyState from '@/components/EmptyState.vue'
import Icon from '@/components/Icon.vue'
import PageHeader from '@/components/PageHeader.vue'
import RadarChart from '@/components/RadarChart.vue'
import StarRating from '@/components/StarRating.vue'

const ev = ref<any>(null), err = ref('')
const mode = ref<'etoiles' | 'pourcent'>('etoiles')
const ouvert = ref<string | null>(null)
const project = useProjectStore()
let seq = 0
/** L'évaluation porte sur le projet en cours : elle se recharge à chaque changement de projet (une réponse d'un autre projet est ignorée). */
async function load() {
  const pid = project.activeId
  if (!pid) return
  const mine = ++seq
  try {
    const r = await api(`/evaluation?projet_id=${pid}`)
    if (mine === seq && pid === project.activeId) { ev.value = r; err.value = '' }
  } catch (e: any) { if (mine === seq && pid === project.activeId) err.value = e.message }
}
usePolling(load, 8000)
watch(() => project.activeId, () => { seq++; ev.value = null; err.value = ''; ouvert.value = null; load() })

const pct = (x: number) => `${Math.round(x * 100)} %`
const sur5 = (x: number) => Math.round(x * 5 * 2) / 2          // demi-étoiles

const t = computed(() => ev.value?.taches)
const r = computed(() => ev.value?.recommandations)
const aTaches = computed(() => (t.value?.proposees ?? 0) > 0)
const aRecos = computed(() => (r.value?.emises ?? 0) > 0)

// Scores (0 à 1) : plus c'est haut, mieux c'est
const scoreTaches = computed(() => (aTaches.value ? Math.min(1, t.value.taux_acceptation_directe + 0.5 * t.value.taux_correction) : null))
const scoreRecos = computed(() => (aRecos.value ? r.value.taux_suivi : null))
const global = computed(() => {
  const s = [scoreTaches.value, scoreRecos.value].filter((x): x is number => x !== null)
  return s.length ? s.reduce((a, b) => a + b, 0) / s.length : null
})
const verdict = computed(() => {
  const g = global.value
  if (g === null) return 'Pas encore de données'
  return g >= 0.85 ? 'Excellent' : g >= 0.7 ? 'Très bon' : g >= 0.5 ? 'Correct' : 'À améliorer'
})

/** `taux` : ligne dont la barre montre le TAUX lui-même (0 % = barre vide ; plus il est bas, mieux c'est). Les notes globales ne changent pas. */
interface Ligne { k: string; titre: string; score: number; valeur: string; aide: string; taux?: boolean }
/** Les étoiles d'une ligne montrent le taux lui-même : 0 % = étoiles grises, elles ne se colorent que selon le vrai pourcentage. */
const note = (l: Ligne) => l.score
const lignesTaches = computed<Ligne[]>(() => !aTaches.value ? [] : [
  { k: 't1', titre: 'Acceptation directe', score: t.value.taux_acceptation_directe, valeur: pct(t.value.taux_acceptation_directe),
    aide: "Tâches validées sans modification ÷ tâches proposées. Plus c'est haut, plus l'agent comprend le cahier des charges." },
  { k: 't2', titre: 'Taux de correction', taux: true, score: t.value.taux_correction, valeur: `${pct(t.value.taux_correction)} des tâches corrigées`,
    aide: 'Taux de correction = tâches modifiées par le haut responsable ÷ tâches proposées. Plus ce taux est bas, plus la note est haute.' },
  { k: 't3', titre: 'Taux de rejet des tâches', taux: true, score: t.value.taux_rejet, valeur: `${pct(t.value.taux_rejet)} des tâches rejetées`,
    aide: "Taux de rejet = tâches supprimées ÷ tâches proposées. Plus ce taux est bas, plus la note est haute." },
])
const lignesRecos = computed<Ligne[]>(() => !aRecos.value ? [] : [
  { k: 'r1', titre: 'Recommandations suivies', score: r.value.taux_suivi, valeur: pct(r.value.taux_suivi),
    aide: "Recommandations suivies ÷ recommandations émises : mesure l'utilité perçue par le haut responsable." },
  { k: 'r2', titre: 'Taux de rejet des recommandations', taux: true, score: r.value.taux_rejet, valeur: `${pct(r.value.taux_rejet)} des recommandations rejetées`,
    aide: 'Taux de rejet = recommandations rejetées ÷ recommandations émises. Plus ce taux est bas, plus la note est haute.' },
])
const axes = computed(() => [
  { label: 'Tâches acceptées', value: aTaches.value ? t.value.taux_acceptation_directe : null },
  { label: 'Taux de correction', value: aTaches.value ? 1 - t.value.taux_correction : null },
  { label: 'Taux de rejet (tâches)', value: aTaches.value ? 1 - t.value.taux_rejet : null },
  { label: 'Recommandations suivies', value: aRecos.value ? r.value.taux_suivi : null },
  { label: 'Taux de rejet (recommandations)', value: aRecos.value ? 1 - r.value.taux_rejet : null },
])
const compte = computed(() => {
  if (!aTaches.value) return null
  const n = t.value.proposees
  return { n, ok: Math.round(t.value.taux_acceptation_directe * n), mod: Math.round(t.value.taux_correction * n), sup: Math.round(t.value.taux_rejet * n) }
})
</script>

<template>
  <PageHeader title="Évaluation de l'IA" :subtitle="project.active ? `Projet « ${project.active.nom} » · qualité des tâches proposées et utilité des recommandations, mesurées sur vos décisions.` : 'Qualité des tâches proposées et utilité des recommandations.'">
    <div class="inline-flex rounded-xl border border-line bg-white p-1 text-xs font-medium" role="tablist" aria-label="Affichage">
      <button v-for="m in (['etoiles', 'pourcent'] as const)" :key="m" role="tab" :aria-selected="mode === m"
        class="rounded-lg px-3 py-1.5 transition" :class="mode === m ? 'bg-brand-600 text-white' : 'text-slate-500 hover:text-slate-900'" @click="mode = m">
        {{ m === 'etoiles' ? 'Étoiles' : 'Pourcentages' }}</button>
    </div>
  </PageHeader>

  <p v-if="err" class="mb-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">{{ err }}</p>

  <template v-if="ev">
    <!-- Profil global : score + radar -->
    <section class="card rise relative overflow-hidden">
      <div class="pointer-events-none absolute -left-24 -top-24 size-72 rounded-full bg-gradient-to-br from-azur/25 to-violet-arato/20 blur-3xl" aria-hidden="true" />
      <div class="relative grid items-center gap-6 p-6 sm:p-10 lg:grid-cols-2">
        <div>
          <p class="eyebrow">Score global de l'agent</p>
          <p class="display mt-3 text-[5rem] font-semibold leading-none tabular-nums sm:text-[6rem]"><span class="grad-text">{{ global === null ? '—' : pct(global).replace(' %', '') }}</span><span v-if="global !== null" class="ml-1 text-3xl text-slate-400">%</span></p>
          <h2 class="display mt-3 text-2xl text-slate-900">{{ verdict }}</h2>
          <div class="mt-3 flex flex-wrap items-center gap-3">
            <StarRating :value="global === null ? 0 : sur5(global)" :size="28" label="Score global" />
            <span v-if="global !== null" class="text-sm tabular-nums text-slate-500"><b class="text-slate-900">{{ sur5(global).toFixed(1) }}</b> / 5</span>
          </div>
          <p class="mt-4 max-w-md text-sm leading-relaxed text-slate-500">
            Moyenne de deux notes : la qualité des tâches proposées à partir des cahiers des charges, et l'utilité des recommandations de suivi.
            {{ global === null ? 'Elles apparaîtront après la validation du cahier de ce projet et vos premières décisions.' : '' }}</p>
          <p v-if="compte" class="mt-5 flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-500">
            <span><b class="tabular-nums text-slate-900">{{ compte.n }}</b> tâches proposées</span>
            <span><b class="tabular-nums text-slate-900">{{ compte.ok }}</b> acceptées</span>
            <span><b class="tabular-nums text-slate-900">{{ compte.mod }}</b> modifiées</span>
            <span><b class="tabular-nums text-slate-900">{{ compte.sup }}</b> supprimées</span>
          </p>
        </div>
        <div>
          <RadarChart :axes="axes" />
          <p class="mt-2 text-center text-xs text-slate-400">Pour les taux de correction et de rejet, la note est le complément du taux : plus il est bas, plus la note est haute.</p>
        </div>
      </div>
    </section>

    <!-- Détail : échelles avec zone cible (70 % et plus) -->
    <div class="mt-6 grid gap-6 lg:grid-cols-2">
      <section v-for="bloc in [
        { id: 'taches', titre: 'Création des tâches', sous: aTaches ? `${t.proposees} tâche(s) proposée(s) par l'agent` : '', icon: 'file', score: scoreTaches, lignes: lignesTaches, vide: ['file', 'Aucune tâche proposée', 'Les notes apparaîtront après la validation du cahier des charges de ce projet.'] },
        { id: 'suivi', titre: 'Suivi', sous: aRecos ? `${r.emises} recommandation(s) émise(s)` : '', icon: 'activity', score: scoreRecos, lignes: lignesRecos, vide: ['activity', 'Aucune recommandation émise', 'Elles apparaîtront dès que l\'agent aura analysé des tickets.'] },
      ]" :key="bloc.id" class="card rise flex flex-col">
        <header class="flex items-center gap-3 border-b border-line px-6 py-4">
          <span class="grid size-9 place-items-center rounded-xl bg-brand-100 text-brand-700"><Icon :name="bloc.icon" :size="18" /></span>
          <div><h2 class="card-title">{{ bloc.titre }}</h2><p class="text-xs text-slate-500">{{ bloc.sous || '—' }}</p></div>
          <template v-if="bloc.score !== null">
            <StarRating v-if="mode === 'etoiles'" class="ml-auto" :value="sur5(bloc.score)" :size="18" :label="bloc.titre" />
            <span v-else class="display ml-auto text-2xl tabular-nums text-slate-900">{{ pct(bloc.score) }}</span>
          </template>
        </header>
        <ul v-if="bloc.lignes.length" class="flex-1 divide-y divide-line px-6">
          <li v-for="l in bloc.lignes" :key="l.k" class="py-4">
            <button class="block w-full text-left" :aria-expanded="ouvert === l.k" @click="ouvert = ouvert === l.k ? null : l.k">
              <span class="flex items-baseline justify-between gap-3">
                <span class="text-sm font-medium text-slate-800">{{ l.titre }}</span>
                <span class="text-xs text-slate-500">{{ l.valeur }}</span>
              </span>
              <span class="mt-2.5 flex items-center gap-3">
                <span class="relative block h-2 flex-1 rounded-full bg-slate-100">
                  <span class="absolute inset-y-0 w-[30%] bg-sky-100" :class="l.taux ? 'left-0 rounded-l-full' : 'right-0 rounded-r-full'" aria-hidden="true" />
                  <span class="absolute inset-y-0 left-0 block rounded-full bg-gradient-to-r from-azur via-primary to-violet-arato transition-all duration-1000 ease-out" :style="{ width: Math.round(l.score * 100) + '%' }" />
                  <span class="absolute top-1/2 size-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-[3px] border-white bg-brand-600 shadow transition-all duration-1000 ease-out" :style="{ left: Math.max(2, Math.min(98, Math.round(l.score * 100))) + '%' }" />
                </span>
                <StarRating v-if="mode === 'etoiles'" :value="sur5(note(l))" :size="15" :label="l.titre" />
                <span v-else class="w-10 text-right text-xs font-semibold tabular-nums text-slate-900">{{ pct(l.score) }}</span>
              </span>
            </button>
            <p v-if="ouvert === l.k" class="mt-3 text-xs leading-relaxed text-slate-500">{{ l.aide }}</p>
          </li>
          <li class="py-3 text-[11px] text-slate-400">Zone claire : objectif (70 % et plus ; pour un taux de rejet ou de correction, 30 % et moins). Les étoiles montrent le pourcentage lui-même (0 % : étoiles grises). Cliquez sur une ligne pour voir comment la note est calculée.</li>
        </ul>
        <EmptyState v-else :icon="bloc.vide[0] as string" :title="bloc.vide[1] as string" :text="bloc.vide[2] as string" />
      </section>
    </div>
  </template>
  <div v-else-if="!err" class="card card-pad text-sm text-slate-500">Chargement…</div>
</template>
