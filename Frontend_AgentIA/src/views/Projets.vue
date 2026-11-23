<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { fmtDate, photoCrm } from '@/services/api'
import { usePolling } from '@/composables/usePolling'
import { useProjectStore, type Projet } from '@/stores/project'
import Avatar from '@/components/Avatar.vue'
import EmptyState from '@/components/EmptyState.vue'
import Icon from '@/components/Icon.vue'

/* Page de transition : après l'étape globale « Cahier des charges », le responsable choisit le projet dans lequel il entre
   pour la phase de suivi. Aucun projet n'est ouvert par défaut. */
const router = useRouter()
const project = useProjectStore()
const q = ref('')
const filtre = ref<'tous' | 'actifs' | 'retard' | 'termines'>('tous')
usePolling(() => project.load(), 4000)

type Etat = { cle: 'vide' | 'termine' | 'retard' | 'surveiller' | 'ok'; label: string; point: string }
function etat(p: Projet): Etat {
  if (!p.nb_tickets) return { cle: 'vide', label: 'Sans tâche', point: 'bg-slate-300' }
  if (p.nb_fermes === p.nb_tickets) return { cle: 'termine', label: 'Terminé', point: 'bg-azur' }
  if (p.nb_en_retard) return { cle: 'retard', label: `${p.nb_en_retard} en retard`, point: 'bg-red-500' }
  if (p.nb_a_surveiller) return { cle: 'surveiller', label: 'À surveiller', point: 'bg-violet-arato' }
  return { cle: 'ok', label: 'Dans les délais', point: 'bg-brand-500' }
}
const compte = computed(() => ({
  tous: project.projets.length,
  actifs: project.projets.filter((p) => etat(p).cle !== 'termine').length,
  retard: project.projets.filter((p) => etat(p).cle === 'retard').length,
  termines: project.projets.filter((p) => etat(p).cle === 'termine').length,
}))
const FILTRES = [
  { k: 'tous', l: 'Tous' }, { k: 'actifs', l: 'En cours' }, { k: 'retard', l: 'En retard' }, { k: 'termines', l: 'Terminés' },
] as const
const liste = computed(() => {
  const n = q.value.trim().toLowerCase()
  return project.projets
    .filter((p) => !n || p.nom.toLowerCase().includes(n))
    .filter((p) => filtre.value === 'tous' || (filtre.value === 'actifs' ? etat(p).cle !== 'termine' : filtre.value === 'retard' ? etat(p).cle === 'retard' : etat(p).cle === 'termine'))
    // du plus récent au plus ancien : l'identifiant croît à chaque création de projet (le projet tout juste créé est donc en tête)
    .sort((a, b) => b.id - a.id)
})
const R = 26, C = 2 * Math.PI * R
const arc = (v: number) => `${(Math.max(0, Math.min(100, v)) / 100) * C} ${C}`

function entrer(p: Projet) {
  project.select(p.id)
  if (project.recentId === p.id) project.recentId = null
  router.push('/tableau')
}
</script>

<template>
  <div class="mx-auto max-w-6xl">
    <!-- En-tête -->
    <header class="rise mb-8 flex flex-wrap items-end gap-4">
      <div class="min-w-0 flex-1">
        <p class="eyebrow">Étape suivante · suivi</p>
        <h1 class="mt-2 text-[1.75rem] font-semibold leading-tight tracking-tight text-slate-900 sm:text-[2.1rem]">Dans quel projet souhaitez-vous entrer ?</h1>
        <p class="mt-2 max-w-2xl text-[15px] leading-relaxed text-slate-500">
          Le cahier des charges est une étape globale. Le suivi, lui, se fait projet par projet : choisissez celui que vous voulez piloter
          pour retrouver sa situation, son évaluation et son historique.</p>
      </div>
      <RouterLink to="/" class="btn-secondary"><Icon name="left" :size="15" /> Cahier des charges</RouterLink>
    </header>

    <!-- Recherche et filtres -->
    <div v-if="project.projets.length" class="mb-6 flex flex-wrap items-center gap-3">
      <div class="relative min-w-[16rem] flex-1 sm:max-w-sm">
        <Icon name="search" :size="15" class="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
        <input v-model="q" type="search" class="input py-2.5 pl-10" placeholder="Rechercher un projet…" aria-label="Rechercher un projet" />
      </div>
      <div class="inline-flex rounded-xl border border-line bg-white p-1 text-sm font-medium" role="tablist" aria-label="Filtrer les projets">
        <button v-for="f in FILTRES" :key="f.k" role="tab" :aria-selected="filtre === f.k" type="button"
          class="rounded-lg px-3.5 py-1.5 transition" :class="filtre === f.k ? 'bg-slate-900 text-white' : 'text-slate-500 hover:text-slate-900'"
          @click="filtre = f.k">{{ f.l }}<span class="ml-1.5 text-xs tabular-nums opacity-60">{{ compte[f.k] }}</span></button>
      </div>
    </div>

    <!-- Chargement -->
    <div v-if="!project.loaded" class="grid gap-5 sm:grid-cols-2 xl:grid-cols-3" aria-busy="true" aria-label="Chargement des projets">
      <div v-for="i in 3" :key="i" class="card relative h-64 overflow-hidden"><div class="shimmer absolute inset-0" /></div>
    </div>

    <p v-else-if="project.error" class="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">{{ project.error }}</p>

    <EmptyState v-else-if="!project.projets.length" icon="folder" title="Aucun projet pour l'instant"
      text="Un projet est créé à la validation d'un cahier des charges. Déposez-en un pour démarrer le suivi.">
      <RouterLink to="/" class="btn-primary">Déposer un cahier des charges</RouterLink>
    </EmptyState>

    <div v-else-if="!liste.length" class="card"><EmptyState icon="search" title="Aucun projet ne correspond" text="Modifiez la recherche ou le filtre pour retrouver un projet." /></div>

    <!-- Cartes de projets -->
    <ul v-else class="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
      <li v-for="(p, i) in liste" :key="p.id" class="rise" :style="{ animationDelay: i * 50 + 'ms' }">
        <button type="button" class="project-card group" :aria-label="`Entrer dans le projet ${p.nom}`" @click="entrer(p)">
          <span class="flex items-start gap-3">
            <span class="grid size-11 shrink-0 place-items-center rounded-xl bg-slate-900 text-white transition group-hover:bg-brand-600"><Icon name="folder" :size="20" /></span>
            <span class="min-w-0 flex-1 text-left">
              <span class="flex items-center gap-2">
                <span class="display block truncate text-[17px] leading-tight text-slate-900" :title="p.nom">{{ p.nom }}</span>
                <span v-if="p.id === project.recentId" class="badge-blue shrink-0">Nouveau</span>
              </span>
              <span class="mt-1 inline-flex items-center gap-1.5 text-xs font-medium text-slate-600">
                <span class="size-2 rounded-full" :class="etat(p).point" />{{ etat(p).label }}
                <span v-if="p.nb_a_surveiller && etat(p).cle === 'retard'" class="text-slate-400">· {{ p.nb_a_surveiller }} à surveiller</span>
              </span>
            </span>
            <!-- Anneau d'avancement -->
            <span class="relative grid size-16 shrink-0 place-items-center" :title="`Avancement moyen déclaré : ${p.avancement} %`">
              <svg viewBox="0 0 64 64" class="size-16 -rotate-90" aria-hidden="true">
                <circle cx="32" cy="32" :r="R" fill="none" stroke="#E3E8F0" stroke-width="6" />
                <circle cx="32" cy="32" :r="R" fill="none" stroke="var(--color-brand-500)" stroke-width="6" stroke-linecap="round"
                  :stroke-dasharray="arc(p.avancement)" class="transition-all duration-700 ease-out" />
              </svg>
              <span class="absolute text-[13px] font-semibold tabular-nums text-slate-900">{{ p.avancement }}<span class="text-[9px] text-slate-400"> %</span></span>
            </span>
          </span>

          <!-- Chiffres clés -->
          <span class="mt-5 grid grid-cols-3 divide-x divide-line rounded-xl border border-line bg-slate-50/70 text-center">
            <span class="px-2 py-2.5"><span class="display block text-lg leading-none tabular-nums text-slate-900">{{ p.nb_tickets }}</span><span class="mt-1 block text-[11px] text-slate-500">tâche{{ p.nb_tickets > 1 ? 's' : '' }}</span></span>
            <span class="px-2 py-2.5"><span class="display block text-lg leading-none tabular-nums" :class="p.nb_en_retard ? 'text-red-600' : 'text-slate-900'">{{ p.nb_en_retard }}</span><span class="mt-1 block text-[11px] text-slate-500">en retard</span></span>
            <span class="px-2 py-2.5"><span class="display block text-lg leading-none tabular-nums text-slate-900">{{ p.nb_fermes }}</span><span class="mt-1 block text-[11px] text-slate-500">terminée{{ p.nb_fermes > 1 ? 's' : '' }}</span></span>
          </span>

          <!-- Équipe et échéance -->
          <span class="mt-4 flex items-center gap-3">
            <span v-if="p.equipe.length" class="flex -space-x-2" :title="p.equipe.map((m) => m.nom).join(', ')">
              <Avatar v-for="m in p.equipe.slice(0, 4)" :key="m.id" :nom="m.nom" :src="photoCrm(m.photo)" :size="28" ring />
              <span v-if="p.equipe.length > 4" class="grid size-7 place-items-center rounded-full bg-slate-100 text-[11px] font-semibold text-slate-600 ring-2 ring-white">+{{ p.equipe.length - 4 }}</span>
            </span>
            <span v-else class="text-xs text-slate-400">Équipe non constituée</span>
            <span class="ml-auto inline-flex items-center gap-1.5 text-xs text-slate-500" :title="p.prochaine_echeance ? 'Prochaine échéance' : 'Échéance finale'">
              <Icon name="calendar" :size="13" />{{ fmtDate(p.prochaine_echeance ?? p.date_limite) }}</span>
          </span>

          <span class="mt-5 flex items-center justify-between border-t border-line pt-4 text-sm font-medium text-slate-900">
            <span>Entrer dans le projet</span>
            <span class="grid size-8 place-items-center rounded-full bg-slate-100 text-slate-700 transition group-hover:translate-x-0.5 group-hover:bg-brand-600 group-hover:text-white"><Icon name="right" :size="15" /></span>
          </span>
        </button>
      </li>
    </ul>
  </div>
</template>
