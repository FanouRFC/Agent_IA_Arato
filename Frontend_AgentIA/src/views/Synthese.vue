<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api, download, fmtDateTime, tid } from '@/services/api'

const s = ref<any>(null)
const err = ref('')
const busy = ref(false)

// Limites d'affichage : au-delà, un bouton « Voir plus / Réduire » apparaît
const MAX_EVO = 3
const MAX_TICKETS = 5
const MAX_RECOS = 3
const showAllEvo = ref(false)
const showAllTickets = ref(false)
const showAllRecos = ref(false)
let timer: number

// ---------- Chargement ----------
async function load() {
  try {
    s.value = await api('/synthese')
    err.value = ''
  } catch (e: any) {
    err.value = e.message
  }
}

async function decide(id: number, decision: 'suivie' | 'rejetee') {
  try {
    await api(`/recommandations/${id}/decision`, { method: 'POST', body: JSON.stringify({ decision }) })
    await load()
  } catch (e: any) {
    err.value = e.message
  }
}

async function refresh() {
  busy.value = true
  const avant = s.value?.id ?? 0
  try {
    await api('/synthese/actualiser', { method: 'POST' })
    // Le LLM local est lent : on attend qu'une nouvelle synthèse apparaisse (max ~3 min)
    for (let i = 0; i < 60; i++) {
      await new Promise(r => setTimeout(r, 3000))
      await load()
      if ((s.value?.id ?? 0) !== avant) break
    }
  } catch (e: any) {
    err.value = e.message
  } finally {
    busy.value = false
  }
}

// La synthèse se met à jour côté serveur à chaque événement ; l'interface l'interroge régulièrement.
onMounted(() => { load(); timer = window.setInterval(load, 8000) })
onUnmounted(() => clearInterval(timer))

// ---------- Compteurs ----------
const kpis = computed(() => !s.value ? [] : [
  {
    n: s.value.nb_en_retard, label: 'en retard', hint: 'Échéance dépassée',
    card: 'border-brick/30 bg-brick-soft/40', icon: 'bg-brick-soft text-brick', num: 'text-brick',
    path: 'M12 9v4m0 4h.01M10.3 3.9 2.4 17.5A2 2 0 0 0 4.1 20.5h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z',
  },
  {
    n: s.value.nb_a_surveiller, label: 'à surveiller', hint: 'Échéance proche',
    card: 'border-ochre/30 bg-ochre-soft/40', icon: 'bg-ochre-soft text-ochre', num: 'text-ochre',
    path: 'M12 6v6l4 2m6-2a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z',
  },
  {
    n: s.value.nb_en_attente, label: 'en attente', hint: 'Bloquées par un motif',
    card: 'border-teal/30 bg-teal-soft/40', icon: 'bg-teal-soft text-teal', num: 'text-teal',
    path: 'M10 9v6m4-6v6m7-3a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z',
  },
])

// ---------- Synthèse : découpage en blocs lisibles ----------
const PREFIX_EVO = 'Depuis la dernière analyse'

function tone(t: string) {
  const x = t.toLowerCase()
  if (x.includes('retard') && !x.includes('aucun retard')) return 'brick'
  if (x.includes('surveiller')) return 'ochre'
  return 'ink'
}

const blocs = computed(() => {
  let txt: string = s.value?.contenu ?? ''
  const i = txt.indexOf(PREFIX_EVO) // déjà affiché dans « Évolutions »
  if (i > 0) txt = txt.slice(0, i)
  const phrases = txt.split(/(?<=[.!?])\s+(?=[A-ZÀ-Ý])/).map(p => p.trim()).filter(Boolean)
  return phrases.map((p, idx) => {
    const m = p.match(/^T-(\d+)\s*:\s*(.+)$/)
    if (m) {
      const texte = m[2] ?? ''
      return { type: 'ticket', id: Number(m[1]), texte, tone: tone(texte) }
    }
    return { type: idx === 0 ? 'lead' : 'texte', texte: p, id: 0, tone: 'ink' }
  })
})

// Ordre d'affichage : accroche → lignes de tickets (repliables) → autres phrases
const lead = computed(() => blocs.value.find(b => b.type === 'lead'))
const ticketBlocs = computed(() => blocs.value.filter(b => b.type === 'ticket'))
const texteBlocs = computed(() => blocs.value.filter(b => b.type === 'texte'))
const ticketsVisibles = computed(() =>
  showAllTickets.value ? ticketBlocs.value : ticketBlocs.value.slice(0, MAX_TICKETS))

const TONE_BADGE: Record<string, string> = {
  brick: 'bg-brick-soft text-brick',
  ochre: 'bg-ochre-soft text-ochre',
  ink: 'bg-line/60 text-ink/80',
}
const TONE_BAR: Record<string, string> = {
  brick: 'border-l-brick',
  ochre: 'border-l-ochre',
  ink: 'border-l-line',
}

// ---------- Date relative ----------
const rtf = new Intl.RelativeTimeFormat('fr', { numeric: 'auto' })
function depuis(d: string) {
  const min = Math.round((new Date(d).getTime() - Date.now()) / 60000)
  if (Math.abs(min) < 1) return "à l'instant"
  if (Math.abs(min) < 60) return rtf.format(min, 'minute')
  if (Math.abs(min) < 1440) return rtf.format(Math.round(min / 60), 'hour')
  return rtf.format(Math.round(min / 1440), 'day')
}

// ---------- Évolutions ----------
const evolutions = computed<string[]>(() => s.value?.evolutions ?? [])
const evoVisibles = computed(() =>
  showAllEvo.value ? evolutions.value : evolutions.value.slice(0, MAX_EVO))

// ---------- Recommandations ----------
const DIAG: Record<string, string> = {
  historique: 'Historique',
  impact_systemique: "Impact sur d'autres tâches",
  manque_de_visibilite: 'Manque de visibilité',
}
const recos = computed<any[]>(() => s.value?.recommandations ?? [])
const recosVisibles = computed(() =>
  showAllRecos.value ? recos.value : recos.value.slice(0, MAX_RECOS))
const toutFallback = computed(
  () => recos.value.length > 0 && recos.value.every(r => r.source === 'fallback'),
)
</script>

<template>
  <!-- En-tête -->
  <div class="flex flex-wrap items-center gap-3">
    <h1 class="text-2xl font-semibold">Situation du projet</h1>
    <div class="ml-auto flex gap-2">
      <button class="btn-quiet" :disabled="busy" @click="refresh">
        {{ busy ? 'Réévaluation en cours…' : 'Réévaluer maintenant' }}
      </button>
      <button class="btn-quiet" @click="download('/rapports/pdf', 'rapport_suivi.pdf')">Rapport PDF</button>
      <button class="btn-quiet" @click="download('/rapports/xlsx', 'rapport_suivi.xlsx')">Rapport Excel</button>
    </div>
  </div>

  <p v-if="err" class="mt-4 text-brick" role="alert">{{ err }}</p>
  <p v-if="!s && !err" class="mt-6 text-ink/70">
    Aucune analyse pour l'instant. Elle apparaît dès le premier événement du CRM ou du calendrier.
  </p>

  <template v-else-if="s">
    <!-- Compteurs -->
    <div class="mt-5 grid gap-3 sm:grid-cols-3">
      <div
        v-for="k in kpis"
        :key="k.label"
        class="flex items-center gap-4 rounded-xl border p-4 transition"
        :class="[k.card, k.n === 0 && 'opacity-60']"
        role="group"
        :aria-label="`${k.n} ${k.label}`"
      >
        <span class="grid h-11 w-11 shrink-0 place-items-center rounded-full" :class="k.icon" aria-hidden="true">
          <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round">
            <path :d="k.path" />
          </svg>
        </span>
        <div class="min-w-0">
          <p class="text-3xl font-semibold leading-none tabular-nums" :class="k.num">{{ k.n }}</p>
          <p class="mt-1 text-sm font-medium">{{ k.label }}</p>
          <p class="text-xs text-ink/60">{{ k.hint }}</p>
        </div>
      </div>
    </div>

    <!-- Synthèse -->
    <section class="panel mt-4 !p-0 overflow-hidden">
      <header class="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-5 py-3">
        <h2 class="text-base font-semibold">Synthèse</h2>
        <span class="ml-auto text-xs text-ink/60" :title="fmtDateTime(s.date)">
          Mise à jour {{ depuis(s.date) }}
        </span>
        <span class="rounded-full bg-line/60 px-2 py-0.5 text-xs text-ink/70">{{ s.declencheur }}</span>
      </header>

      <div class="px-5 py-4">
        <!-- Accroche -->
        <p v-if="lead" class="text-lg font-semibold leading-snug">{{ lead.texte }}</p>

        <!-- Tickets (repliables) -->
        <div v-for="b in ticketsVisibles" :key="b.id"
             class="mt-2 flex items-start gap-3 rounded-lg border-l-4 bg-line/20 px-3 py-2.5"
             :class="TONE_BAR[b.tone]">
          <span class="shrink-0 rounded px-1.5 py-0.5 text-xs font-semibold tabular-nums" :class="TONE_BADGE[b.tone]">
            {{ tid(b.id) }}
          </span>
          <p class="text-sm leading-relaxed">{{ b.texte }}</p>
        </div>
        <button
          v-if="ticketBlocs.length > MAX_TICKETS"
          class="mt-2 text-sm font-medium text-teal underline-offset-2 hover:underline"
          :aria-expanded="showAllTickets"
          @click="showAllTickets = !showAllTickets"
        >
          {{ showAllTickets ? 'Réduire' : `Voir les ${ticketBlocs.length - MAX_TICKETS} autres tickets` }}
        </button>

        <!-- Autres phrases -->
        <p v-for="(b, i) in texteBlocs" :key="i" class="mt-3 max-w-prose text-[15px] leading-7 text-ink/90">
          {{ b.texte }}
        </p>

        <p v-if="!blocs.length" class="text-ink/70">Aucun contenu.</p>
      </div>

      <!-- Évolutions -->
      <footer v-if="evolutions.length" class="border-t border-line bg-line/20 px-5 py-3">
        <p class="text-sm font-semibold text-ink/80">
          Depuis la dernière analyse
          <span class="ml-1 rounded-full bg-line px-1.5 py-0.5 text-xs font-medium">{{ evolutions.length }}</span>
        </p>
        <ul class="mt-2 space-y-1.5">
          <li v-for="e in evoVisibles" :key="e" class="flex gap-2 text-sm">
            <span class="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-ink/40" aria-hidden="true"></span>{{ e }}
          </li>
        </ul>
        <button
          v-if="evolutions.length > MAX_EVO"
          class="mt-2 text-sm font-medium text-teal underline-offset-2 hover:underline"
          :aria-expanded="showAllEvo"
          @click="showAllEvo = !showAllEvo"
        >
          {{ showAllEvo ? 'Réduire' : `Voir les ${evolutions.length - MAX_EVO} autres` }}
        </button>
      </footer>
    </section>

    <!-- Recommandations -->
    <section class="mt-6">
      <h2 class="flex items-center gap-2 text-lg font-semibold">
        Recommandations à examiner
        <span v-if="recos.length" class="rounded-full bg-line px-2 py-0.5 text-xs font-medium">{{ recos.length }}</span>
      </h2>

      <p v-if="toutFallback" class="panel mt-2 border-l-4 border-l-ochre text-sm" role="status">
        Ces recommandations viennent des règles automatiques : le modèle d'IA n'a pas produit de réponse conforme.
      </p>

      <p v-if="!recos.length" class="mt-2 text-ink/70">Aucune recommandation en attente de décision.</p>

      <div v-for="r in recosVisibles" :key="r.id" class="panel mt-3 flex flex-wrap items-center gap-3">
        <div class="max-w-3xl flex-1">
          <p class="flex flex-wrap items-center gap-2 text-xs text-ink/60">
            <span v-if="r.id_ticket" class="font-semibold text-ink/80">{{ tid(r.id_ticket) }}</span>
            <span
              v-if="r.source"
              class="rounded px-1.5 py-0.5"
              :class="r.source === 'fallback' ? 'bg-ochre-soft text-ochre' : 'bg-teal-soft text-teal'"
            >
              {{ r.source === 'fallback' ? 'Règle automatique' : 'Analyse IA' }}
            </span>
            <span v-if="r.diagnostic && DIAG[r.diagnostic]">{{ DIAG[r.diagnostic] }}</span>
            <span v-if="r.date">{{ depuis(r.date) }}</span>
          </p>
          <p class="mt-1 leading-relaxed">{{ r.texte }}</p>
        </div>
        <button class="btn" @click="decide(r.id, 'suivie')">Suivre</button>
        <button class="btn-quiet" @click="decide(r.id, 'rejetee')">Rejeter</button>
      </div>

      <button
        v-if="recos.length > MAX_RECOS"
        class="mt-3 text-sm font-medium text-teal underline-offset-2 hover:underline"
        :aria-expanded="showAllRecos"
        @click="showAllRecos = !showAllRecos"
      >
        {{ showAllRecos ? 'Réduire' : `Voir les ${recos.length - MAX_RECOS} autres recommandations` }}
      </button>
    </section>
  </template>
</template>
