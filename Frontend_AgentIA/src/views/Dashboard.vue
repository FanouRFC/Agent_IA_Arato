<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, fmtDate, SITUATION_CLASS, STATUT, tid } from '@/services/api'

type Cle = 'urgence' | 'ticket' | 'statut' | 'avancement'

const PAGE = 20
const SITUATIONS = [
  { k: 'en_retard', l: 'En retard', dot: 'bg-brick' },
  { k: 'a_surveiller', l: 'À surveiller', dot: 'bg-ochre' },
  { k: 'normale', l: 'Dans les temps', dot: 'bg-teal' },
]
const ORDRE_SIT: Record<string, number> = { en_retard: 0, a_surveiller: 1, normale: 2, ferme: 3 }
const BAR_SIT: Record<string, string> = { en_retard: 'bg-brick', a_surveiller: 'bg-ochre', normale: 'bg-teal', ferme: 'bg-ink/30' }
const STATUT_ORDRE = Object.keys(STATUT)
const COLS: { k: Cle | ''; l: string }[] = [
  { k: 'ticket', l: 'Ticket' },
  { k: 'statut', l: 'Statut CRM' },
  { k: 'avancement', l: 'Avancement déclaré' },
  { k: 'urgence', l: "État de l'échéance" },
  { k: '', l: 'Motif documenté' },
]
const CHIP_ON = 'border-ink bg-ink text-white'
const CHIP_OFF = 'border-line hover:border-ink/40'

// ---------- État ----------
const route = useRoute()
const router = useRouter()
const str = (v: unknown) => (typeof v === 'string' ? v : '')

const rows = ref<any[]>([])
const loading = ref(false)
const err = ref('')
const q = ref(str(route.query.q))
const statut = ref(str(route.query.statut))
const situation = ref(str(route.query.situation))
const projet = ref(str(route.query.projet))
const tri = ref<{ cle: Cle; dir: 1 | -1 }>({ cle: 'urgence', dir: 1 })
const showAll = ref(false)
const searchEl = ref<HTMLInputElement | null>(null)

async function load() {
  loading.value = true
  err.value = ''
  try {
    rows.value = await api('/dashboard')
  } catch (e: any) {
    err.value = e.message
  } finally {
    loading.value = false
  }
}

function onKey(e: KeyboardEvent) {
  const el = e.target as HTMLElement | null
  const typing = !!el && (['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) || el.isContentEditable)
  if (e.key === '/' && !typing && !e.ctrlKey && !e.metaKey) {
    e.preventDefault()
    searchEl.value?.focus()
  }
}
onMounted(() => { load(); window.addEventListener('keydown', onKey) })
onUnmounted(() => window.removeEventListener('keydown', onKey))

// Les filtres restent dans l'adresse : la page se retrouve identique après un retour ou un rechargement
watch([q, statut, situation, projet], () => {
  showAll.value = false
  router.replace({
    query: {
      ...route.query,
      q: q.value || undefined,
      statut: statut.value || undefined,
      situation: situation.value || undefined,
      projet: projet.value || undefined,
    },
  })
})

// ---------- Recherche ----------
const norm = (s: string) => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const tokens = computed(() => norm(q.value).split(/\s+/).filter(Boolean))

function haystack(r: any) {
  return norm([tid(r.id), r.titre, r.projet, r.motif, r.etat_echeance, STATUT[r.statut]].filter(Boolean).join(' '))
}
function matchToken(r: any, tok: string) {
  // « t-14 », « T014 » ou « #14 » retrouvent le ticket T-014
  const m = tok.match(/^(?:t-?|#)0*(\d+)$/)
  if (m && Number(m[1]) === r.id) return true
  return haystack(r).includes(tok)
}
const matchQuery = (r: any) => tokens.value.every(t => matchToken(r, t))

function parts(text: string | null | undefined) {
  const t = text ?? ''
  const toks = tokens.value.filter(x => x.length > 1)
  const n = norm(t)
  if (!t || !toks.length || n.length !== t.length) return [{ t, hit: false }]
  const re = new RegExp('(' + toks.map(escapeRe).join('|') + ')', 'g')
  const out: { t: string; hit: boolean }[] = []
  let last = 0
  for (const m of n.matchAll(re)) {
    const i = m.index ?? 0
    if (i > last) out.push({ t: t.slice(last, i), hit: false })
    out.push({ t: t.slice(i, i + m[0].length), hit: true })
    last = i + m[0].length
  }
  if (last < t.length) out.push({ t: t.slice(last), hit: false })
  return out
}

// ---------- Filtres ----------
function pass(r: any, skip?: 'statut' | 'situation' | 'projet') {
  return (skip === 'statut' || !statut.value || r.statut === statut.value)
    && (skip === 'situation' || !situation.value || r.situation === situation.value)
    && (skip === 'projet' || !projet.value || r.projet === projet.value)
    && matchQuery(r)
}
// Les compteurs tiennent compte de la recherche et des autres filtres
const countStatut = (s: string) => rows.value.filter(r => pass(r, 'statut') && r.statut === s).length
const countSituation = (s: string) => rows.value.filter(r => pass(r, 'situation') && r.situation === s).length
const projets = computed(() => [...new Set(rows.value.map(r => r.projet).filter(Boolean))].sort() as string[])
const filtresActifs = computed(() => !!(q.value || statut.value || situation.value || projet.value))
function reinitialiser() {
  q.value = ''
  statut.value = ''
  situation.value = ''
  projet.value = ''
}

// ---------- Tri ----------
function trier(cle: Cle) {
  tri.value = tri.value.cle === cle ? { cle, dir: tri.value.dir === 1 ? -1 : 1 } : { cle, dir: 1 }
}
const fleche = (cle: string) => (tri.value.cle === cle ? (tri.value.dir === 1 ? '▲' : '▼') : '')
const ariaSort = (cle: string) =>
  tri.value.cle === cle ? (tri.value.dir === 1 ? 'ascending' : 'descending') : 'none'

const filtered = computed(() => rows.value.filter(r => pass(r)))
const sorted = computed(() => {
  const { cle, dir } = tri.value
  const num = (r: any): number =>
    cle === 'ticket' ? r.id
      : cle === 'statut' ? STATUT_ORDRE.indexOf(r.statut)
      : cle === 'avancement' ? Number(r.avancement_declare) || 0
      : ORDRE_SIT[r.situation] ?? 9
  const date = (r: any): string => r.echeance ?? '9999-12-31'
  return [...filtered.value].sort((a, b) => (num(a) - num(b)) * dir || date(a).localeCompare(date(b)) || a.id - b.id)
})
const visibles = computed(() => (showAll.value ? sorted.value : sorted.value.slice(0, PAGE)))
</script>

<template>
  <div class="flex flex-wrap items-end gap-3">
    <div>
      <h1 class="text-2xl font-semibold">Tableau de bord</h1>
      <p class="mt-1 text-sm text-ink/70">
        Le statut CRM, l'avancement déclaré et l'état de l'échéance sont trois informations distinctes.
      </p>
    </div>
    <button class="btn-quiet ml-auto" :disabled="loading" @click="load">
      {{ loading ? 'Actualisation…' : 'Actualiser' }}
    </button>
  </div>

  <div v-if="err" class="panel mt-4 flex flex-wrap items-center gap-3 border-l-4 border-l-brick" role="alert">
    <p class="flex-1 text-sm text-brick">{{ err }}</p>
    <button class="btn-quiet" @click="load">Réessayer</button>
  </div>

  <!-- Recherche -->
  <div class="relative mt-5 max-w-2xl">
    <svg class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink/50" viewBox="0 0 24 24"
         fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
      <circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" />
    </svg>
    <input ref="searchEl" v-model="q" type="text" autocomplete="off" class="field pl-9! pr-10!"
           placeholder="Rechercher un ticket (T-014), un titre, un projet, un motif…" aria-label="Rechercher un ticket"
           @keydown.esc="q = ''" />
    <button v-if="q" type="button" class="absolute right-2 top-1/2 grid h-7 w-7 -translate-y-1/2 place-items-center rounded text-ink/60 hover:bg-line/50"
            aria-label="Effacer la recherche" @click="q = ''; searchEl?.focus()">✕</button>
    <kbd v-else class="pointer-events-none absolute right-3 top-1/2 hidden -translate-y-1/2 rounded border border-line px-1.5 text-xs text-ink/50 sm:block"
         aria-hidden="true">/</kbd>
  </div>

  <!-- Filtres -->
  <div class="mt-4 flex flex-wrap items-center gap-x-6 gap-y-3 text-sm">
    <div class="flex flex-wrap items-center gap-2" role="group" aria-label="Filtrer par statut CRM">
      <span class="text-ink/60">Statut</span>
      <button v-for="s in STATUT_ORDRE" :key="s" type="button" class="rounded-full border px-3 py-1 transition"
              :class="statut === s ? CHIP_ON : CHIP_OFF" :aria-pressed="statut === s"
              @click="statut = statut === s ? '' : s">
        {{ STATUT[s] }} <span class="tabular-nums opacity-70">{{ countStatut(s) }}</span>
      </button>
    </div>

    <div class="flex flex-wrap items-center gap-2" role="group" aria-label="Filtrer par état de l'échéance">
      <span class="text-ink/60">Échéance</span>
      <button v-for="s in SITUATIONS" :key="s.k" type="button"
              class="flex items-center gap-1.5 rounded-full border px-3 py-1 transition"
              :class="situation === s.k ? CHIP_ON : CHIP_OFF" :aria-pressed="situation === s.k"
              @click="situation = situation === s.k ? '' : s.k">
        <span class="h-2 w-2 rounded-full" :class="s.dot" aria-hidden="true"></span>
        {{ s.l }} <span class="tabular-nums opacity-70">{{ countSituation(s.k) }}</span>
      </button>
    </div>

    <label v-if="projets.length > 1" class="flex items-center gap-2">
      <span class="text-ink/60">Projet</span>
      <select v-model="projet" class="field w-auto! py-1!">
        <option value="">Tous</option>
        <option v-for="p in projets" :key="p" :value="p">{{ p }}</option>
      </select>
    </label>

    <button v-if="filtresActifs" type="button" class="text-teal hover:underline" @click="reinitialiser">
      Réinitialiser
    </button>
  </div>

  <p class="mt-4 text-sm text-ink/60" aria-live="polite">
    <template v-if="rows.length">
      {{ filtered.length }} ticket{{ filtered.length > 1 ? 's' : '' }}
      <template v-if="filtered.length !== rows.length">sur {{ rows.length }}</template>
    </template>
  </p>

  <!-- Tableau -->
  <div class="panel mt-2 overflow-x-auto p-0!">
    <table class="w-full min-w-[46rem] text-left text-sm">
      <thead class="border-b border-line bg-paper">
        <tr>
          <th v-for="c in COLS" :key="c.l" class="p-3" scope="col" :aria-sort="c.k ? ariaSort(c.k) : undefined">
            <button v-if="c.k" type="button" class="inline-flex items-center gap-1 font-semibold hover:text-teal"
                    @click="trier(c.k)">
              {{ c.l }}<span class="w-3 text-xs" aria-hidden="true">{{ fleche(c.k) }}</span>
            </button>
            <template v-else>{{ c.l }}</template>
          </th>
        </tr>
      </thead>
      <tbody>
        <!-- Chargement -->
        <template v-if="loading && !rows.length">
          <tr v-for="i in 5" :key="i" class="border-b border-line/60" aria-hidden="true">
            <td v-for="j in 5" :key="j" class="p-3"><div class="h-4 animate-pulse rounded bg-line/60"></div></td>
          </tr>
        </template>

        <tr v-for="r in visibles" :key="r.id" class="border-b border-line/60 align-top transition hover:bg-line/20">
          <td class="p-3">
            <router-link :to="`/tickets/${r.id}`" class="font-medium text-teal underline">{{ tid(r.id) }}</router-link>
            <span v-if="r.projet" class="ml-2 text-xs text-ink/50">{{ r.projet }}</span>
            <div class="mt-0.5 max-w-xs text-sm text-ink/80">
              <template v-for="(p, i) in parts(r.titre)" :key="i">
                <mark v-if="p.hit" class="rounded bg-ochre-soft px-0.5 text-inherit">{{ p.t }}</mark>
                <template v-else>{{ p.t }}</template>
              </template>
            </div>
          </td>
          <td class="p-3"><span class="tag bg-line/60 text-ink/80">{{ STATUT[r.statut] ?? r.statut }}</span></td>
          <td class="p-3">
            <div class="flex items-center gap-2">
              <span class="h-1.5 w-20 overflow-hidden rounded-full bg-line" aria-hidden="true">
                <span class="block h-full rounded-full" :class="BAR_SIT[r.situation] ?? 'bg-teal'"
                      :style="{ width: Math.min(100, Math.max(0, Number(r.avancement_declare) || 0)) + '%' }"></span>
              </span>
              <span class="tabular-nums">{{ r.avancement_declare }} %</span>
            </div>
          </td>
          <td class="p-3">
            <span class="tag" :class="SITUATION_CLASS[r.situation]">{{ r.etat_echeance }}</span>
            <div class="mt-1 text-xs text-ink/60">échéance {{ fmtDate(r.echeance) }}</div>
          </td>
          <td class="p-3">
            <template v-if="r.motif">
              <template v-for="(p, i) in parts(r.motif)" :key="i">
                <mark v-if="p.hit" class="rounded bg-ochre-soft px-0.5 text-inherit">{{ p.t }}</mark>
                <template v-else>{{ p.t }}</template>
              </template>
            </template>
            <span v-else-if="r.situation === 'en_retard'" class="italic text-ochre">Aucun motif documenté</span>
            <span v-else class="text-ink/40">—</span>
          </td>
        </tr>

        <tr v-if="!loading && !visibles.length">
          <td colspan="5" class="p-8 text-center">
            <template v-if="rows.length">
              <p class="text-ink/70">Aucun ticket ne correspond à votre recherche.</p>
              <button class="btn-quiet mt-3" @click="reinitialiser">Réinitialiser les filtres</button>
            </template>
            <p v-else class="text-ink/60">Aucun ticket pour l'instant.</p>
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <button v-if="sorted.length > PAGE" class="mt-3 text-sm font-medium text-teal underline-offset-2 hover:underline"
          :aria-expanded="showAll" @click="showAll = !showAll">
    {{ showAll ? 'Réduire' : `Voir les ${sorted.length - PAGE} autres tickets` }}
  </button>
</template>
