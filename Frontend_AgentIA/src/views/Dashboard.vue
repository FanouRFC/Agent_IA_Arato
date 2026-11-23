<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api, fmtDate, photoCrm, STATUT, tid } from '@/services/api'
import { usePolling } from '@/composables/usePolling'
import { useProjectStore } from '@/stores/project'
import Avatar from '@/components/Avatar.vue'
import EmptyState from '@/components/EmptyState.vue'
import Icon from '@/components/Icon.vue'
import StatutBadge from '@/components/StatutBadge.vue'

const router = useRouter()
const onglet = ref<'frise' | 'avancement'>('frise')
const project = useProjectStore()
const d = ref<any>(null), err = ref(''), filtre = ref('tous'), q = ref('')
const tri = ref<{ k: string; asc: boolean }>({ k: 'urgence', asc: true })

async function load() {
  if (!project.activeId) return
  try { d.value = await api(`/projets/${project.activeId}/dashboard`); err.value = '' } catch (e: any) { err.value = e.message }
}
usePolling(load, 4000)
watch(() => project.activeId, () => { d.value = null; filtre.value = 'tous'; q.value = ''; membreF.value = null; load() })

const stats = computed(() => d.value?.stats)
const total = computed(() => stats.value?.total || 0)
const rows = computed<any[]>(() => d.value?.tickets ?? [])
const roster = computed<Record<number, any>>(() => Object.fromEntries((d.value?.membres ?? []).map((m: any) => [m.id, m])))

// Palette : corail = retard, ambre = à surveiller, bleu acier = dans les délais, gris = terminées
const segments = computed(() => {
  const st = stats.value
  if (!st) return []
  const autres = st.total - st.en_retard - st.a_surveiller - st.par_statut.ferme
  return [
    { k: 'en_retard', label: 'En retard', value: st.en_retard, color: 'var(--nx-late)' },
    { k: 'a_surveiller', label: 'À surveiller', value: st.a_surveiller, color: 'var(--nx-watch)' },
    { k: 'normale', label: 'Dans les délais', value: Math.max(0, autres), color: 'var(--nx-ok)' },
    { k: 'ferme', label: 'Terminées', value: st.par_statut.ferme, color: 'var(--nx-done)' },
  ]
})
const sante = computed(() => (total.value ? Math.round(((total.value - (stats.value?.en_retard ?? 0) - (stats.value?.a_surveiller ?? 0)) / total.value) * 100) : 0))
const verdict = computed(() => (sante.value >= 80 ? 'Le projet est sous contrôle' : sante.value >= 50 ? 'Le projet demande de l\'attention' : 'Le projet est en difficulté'))
const survol = ref('')
const jour = (d: Date) => d.toLocaleDateString('sv-SE')
/** Échéances des 14 prochains jours (tickets non fermés) : une colonne par jour, les retards à part. */
const agenda = computed(() => {
  const auj = new Date(); auj.setHours(0, 0, 0, 0)
  const jours = Array.from({ length: 14 }, (_, i) => { const x = new Date(auj); x.setDate(auj.getDate() + i); return x })
  const ouverts = rows.value.filter((r) => r.statut !== 'ferme')
  const cols = jours.map((x) => ({ d: x, n: ouverts.filter((r) => String(r.echeance).slice(0, 10) === jour(x)).length }))
  const max = Math.max(1, ...cols.map((c) => c.n))
  const prochains = ouverts.filter((r) => String(r.echeance).slice(0, 10) >= jour(auj)).sort((a, b) => cmp(a.echeance, b.echeance)).slice(0, 5)
  return { cols, max, prochains, retards: ouverts.filter((r) => String(r.echeance).slice(0, 10) < jour(auj)).length }
})
const lettre = (d: Date) => d.toLocaleDateString('fr-FR', { weekday: 'narrow' }).toUpperCase()
const mois = (iso: string) => new Date(iso).toLocaleDateString('fr-FR', { month: 'short' }).replace('.', '')
const jourNum = (iso: string) => new Date(iso).getDate()
// Jauge de santé (affichage) : un arc par situation, proportionnel au nombre de tickets ; l'aiguille indique le % sans alerte
const arcs = computed(() => {
  let cumul = 0
  return segments.value.filter((g) => g.value).map((g) => {
    const part = total.value ? (g.value / total.value) * 100 : 0
    const out = { ...g, start: cumul, len: Math.max(0, part - 1.2) }
    cumul += part
    return out
  })
})
/** Frise : tickets non terminés rangés par jour d'échéance (14 jours) ; les retards forment la première colonne. */
const frise = computed(() => {
  const auj = new Date(); auj.setHours(0, 0, 0, 0)
  const ouverts = rows.value.filter((r) => r.statut !== 'ferme')
  const cols = Array.from({ length: 14 }, (_, i) => { const x = new Date(auj); x.setDate(auj.getDate() + i); return { d: x, we: x.getDay() === 0 || x.getDay() === 6, items: ouverts.filter((r) => String(r.echeance).slice(0, 10) === jour(x)) } })
  const retards = ouverts.filter((r) => String(r.echeance).slice(0, 10) < jour(auj))
  return { cols, retards, total: retards.length + cols.reduce((n, c) => n + c.items.length, 0) }
})
// Avancement déclaré des tickets en cours (l'avancement n'apparaît plus dans le tableau : il est ici)
const avancements = computed(() => rows.value.filter((r) => r.statut !== 'ferme')
  .sort((a, b) => b.avancement_declare - a.avancement_declare).slice(0, 6)
  .map((r) => ({ label: `${tid(r.id)} · ${r.titre}`, value: r.avancement_declare, color: r.situation === 'en_retard' ? 'var(--nx-late)' : 'var(--nx-ok)', hint: r.etat_echeance })))

// Charge par membre : tickets non fermés. Jauge circulaire fine + badge de charge (légère / modérée / élevée).
const CAPACITE = 6
const niveau = (n: number) => (n >= 5 ? { l: 'Élevée', cls: 'badge-red' } : n >= 3 ? { l: 'Modérée', cls: 'badge-amber' } : { l: 'Légère', cls: 'badge-slate' })
const ABREGE: Record<string, string> = { nouveau: 'Nouv.', ouvert: 'Ouv.', en_cours: 'Cours', en_attente: 'Att.', retard: 'Ret.' }
const COLS_CHARGE = [
  { k: 'nouveau', l: 'Nouveau' }, { k: 'ouvert', l: 'Ouvert' }, { k: 'en_cours', l: 'En cours' }, { k: 'en_attente', l: 'En attente' }, { k: 'retard', l: 'En retard' },
]
const membreF = ref<number | null>(null)
/** Matrice membre × statut : chaque case compte les tickets non terminés ; la dernière colonne compte les retards. */
const charge = computed(() => {
  const m = new Map<number, { n: number; late: number; par: Record<string, number> }>()
  for (const r of rows.value) {
    if (r.statut === 'ferme') continue
    for (const id of r.membre_ids ?? []) {
      const x = m.get(id) ?? { n: 0, late: 0, par: {} }
      x.n++; x.par[r.statut] = (x.par[r.statut] ?? 0) + 1
      if (r.situation === 'en_retard') { x.late++; x.par.retard = (x.par.retard ?? 0) + 1 }
      m.set(id, x)
    }
  }
  return [...m.entries()].sort((a, b) => b[1].n - a[1].n).slice(0, 8).map(([id, x]) => {
    const mb = roster.value[id]
    return { id, nom: mb?.nom ?? 'Membre', photo: photoCrm(mb?.photo), ...x, niv: niveau(x.n) }
  })
})

const maxCase = computed(() => Math.max(1, ...charge.value.flatMap((c) => COLS_CHARGE.map((k) => c.par[k.k] ?? 0))))
const intensite = (n: number) => ({ '--t': (0.14 + 0.66 * (n / maxCase.value)).toFixed(2) })
const fort = (n: number) => n / maxCase.value > 0.5
const filtreActif = computed(() => filtre.value !== 'tous' || !!q.value.trim() || membreF.value !== null)
function reinitialiser() { filtre.value = 'tous'; q.value = ''; membreF.value = null }
const filtreNom = computed(() => (membreF.value === null ? '' : roster.value[membreF.value]?.nom ?? ''))
const count = (f: string) => rows.value.filter((r) => match(r, f)).length
function match(r: any, f: string) {
  if (membreF.value !== null && !(r.membre_ids ?? []).includes(membreF.value)) return false
  if (f === 'tous') return true
  if (f === 'en_retard' || f === 'a_surveiller') return r.situation === f
  return r.statut === f
}
const FILTRES = [
  { k: 'tous', l: 'Tous' }, { k: 'nouveau', l: STATUT.nouveau }, { k: 'ouvert', l: STATUT.ouvert }, { k: 'en_cours', l: STATUT.en_cours },
  { k: 'en_attente', l: STATUT.en_attente }, { k: 'ferme', l: STATUT.ferme }, { k: 'en_retard', l: 'En retard' }, { k: 'a_surveiller', l: 'À surveiller' },
]

// Tri : par défaut, les tickets les plus urgents en premier (retard, à surveiller, puis échéance)
const ORDRE_SITUATION: Record<string, number> = { en_retard: 0, a_surveiller: 1, normale: 2, ferme: 3 }
const valeurTri = (r: any, k: string) =>
  k === 'urgence' ? (ORDRE_SITUATION[r.situation] ?? 9) : k === 'titre' ? r.titre.toLowerCase() : k === 'statut' ? r.statut : k === 'avancement' ? r.avancement_declare : r.echeance
const cmp = (a: any, b: any) => (a < b ? -1 : a > b ? 1 : 0)
const shown = computed(() => {
  const needle = q.value.trim().toLowerCase()
  const list = rows.value.filter((r) => match(r, filtre.value) && (!needle || (tid(r.id) + ' ' + r.titre).toLowerCase().includes(needle)))
  const { k, asc } = tri.value
  return [...list].sort((a, b) => {
    let c = cmp(valeurTri(a, k), valeurTri(b, k))
    if (c === 0) c = cmp(a.echeance, b.echeance)
    return asc ? c : -c
  })
})
function trier(k: string) { tri.value = { k, asc: tri.value.k === k ? !tri.value.asc : true } }
const fleche = (k: string) => (tri.value.k === k ? (tri.value.asc ? '↑' : '↓') : '')
const ariaSort = (k: string) => (tri.value.k === k ? (tri.value.asc ? 'ascending' : 'descending') : 'none')
// Colonnes : statut CRM, état de l'échéance (calculé par Python) et avancement déclaré par le membre.
const COLS = [{ k: 'titre', l: 'Ticket' }, { k: 'statut', l: 'Statut' }, { k: 'urgence', l: "État de l'échéance" }, { k: 'avancement', l: 'Avancement' }]
const accentLigne = (r: any) => (r.situation === 'en_retard' ? 'var(--nx-late)' : r.situation === 'a_surveiller' ? 'var(--nx-watch)' : r.situation === 'ferme' ? 'var(--nx-line-3)' : 'var(--nx-ok)')
const equipe = (r: any) => (r.membre_ids ?? []).map((id: number) => roster.value[id]).filter(Boolean)
</script>


<template>
  <div class="nx">
    <header class="nx-head nx-in">
      <div class="min-w-0 flex-1">
        <p class="nx-eyebrow mb-2">Suivi · {{ d ? d.projet.nom : 'Projet' }}</p>
        <h1>Tableau de bord</h1>
        <p>{{ d ? `${d.stats.total} tickets suivis en direct` : 'Suivi rapide des tickets du projet' }}</p>
      </div>
    </header>

    <p v-if="err" class="mb-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">{{ err }}</p>

    <div v-if="!d && !err" class="nx-dash" aria-busy="true">
      <div class="nx-skel nx-s7" style="height: 22rem" /><div class="nx-skel nx-s5" style="height: 22rem" />
    </div>

    <div v-if="d" class="nx-dash">
      <!-- NIVEAU 1 · l'état du projet (bloc signature) + la charge de l'équipe juste à côté -->
      <h2 class="nx-niveau nx-s12"><span>1</span>Vue d'ensemble<small>État du projet et charge de l'équipe</small></h2>
      <section class="nx-hero nx-s7 nx-in" style="--i: 1" aria-label="État du projet">
        <p class="nx-hero-top"><span class="nx-live" aria-hidden="true" />État du projet · en direct</p>
        <div class="nx-hero-grid">
          <div class="nx-gauge">
            <div class="nx-gauge-ring">
            <svg viewBox="0 0 200 200" role="img" :aria-label="`Santé du projet : ${sante} %. ${segments.map((g) => `${g.value} ${g.label}`).join(', ')}`">
              <circle cx="100" cy="100" r="82" pathLength="100" class="g-fond" />
              <circle v-for="g in arcs" :key="g.k" cx="100" cy="100" r="82" pathLength="100" class="g-arc" transform="rotate(-90 100 100)"
                :style="{ stroke: g.color, strokeDasharray: `${Math.max(0.5, g.len - 2.2)} ${100 - Math.max(0.5, g.len - 2.2)}`, strokeDashoffset: -(g.start + 1.1), opacity: survol && survol !== g.k ? .2 : 1 }"
                @mouseenter="survol = g.k" @mouseleave="survol = ''" />
            </svg>
            <div class="nx-gauge-c"><p class="nx-num">{{ sante }}<span>%</span></p></div>
            </div>
            <p class="nx-verdict">{{ verdict }}</p>
            <p class="nx-verdict-s">{{ total - stats.en_retard - stats.a_surveiller }} des {{ total }} tickets sans alerte</p>
          </div>
          <div class="nx-kpis">
            <button v-for="k in [
              { f: 'en_retard', l: 'En retard', v: stats.en_retard, n: stats.en_retard, i: 'alert', c: 'var(--nx-late)', t: 'Priorité' },
              { f: 'a_surveiller', l: 'À surveiller', v: stats.a_surveiller, n: stats.a_surveiller, i: 'clock', c: 'var(--nx-watch)', t: 'Proche' },
              { f: 'en_attente', l: 'En attente', v: stats.par_statut.en_attente, n: stats.par_statut.en_attente, i: 'lock', c: '#C3CDDC', t: 'Bloquées' },
              { f: 'ferme', l: 'Terminées', v: `${stats.par_statut.ferme}`, n: stats.par_statut.ferme, i: 'check', c: 'var(--nx-done)', t: `sur ${stats.total}` },
            ]" :key="k.f" type="button" class="nx-kpi" :class="filtre === k.f && 'is-on'" :aria-pressed="filtre === k.f"
              @click="filtre = filtre === k.f ? 'tous' : k.f" @mouseenter="survol = k.f === 'ferme' ? 'ferme' : k.f" @mouseleave="survol = ''">
              <Icon :name="k.i" :size="16" class="nx-kpi-ico" />
              <span class="nx-kpi-l"><i :style="{ background: k.c }" />{{ k.l }}</span>
              <span class="nx-kpi-v nx-num">{{ k.v }}</span>
              <span class="nx-kpi-p">{{ k.t }} · {{ total ? Math.round((k.n / total) * 100) : 0 }} %</span>
            </button>
          </div>
        </div>
        <div class="nx-seg" role="img" :aria-label="segments.map((g) => `${g.value} ${g.label}`).join(', ')">
          <button v-for="g in segments.filter((x) => x.value)" :key="g.k" type="button" :style="{ flexGrow: g.value, background: g.color, opacity: survol && survol !== g.k ? .3 : 1 }"
            :title="`${g.value} ${g.label} · cliquer pour filtrer`" @mouseenter="survol = g.k" @mouseleave="survol = ''" @click="filtre = g.k === 'normale' ? 'tous' : g.k">{{ g.value }}</button>
        </div>
        <dl class="nx-hero-rep">
          <div><dt><Icon name="calendar" :size="13" /> Échéance finale</dt><dd>{{ d.projet.date_limite ? fmtDate(d.projet.date_limite) : '—' }}</dd></div>
          <div><dt><Icon name="clock" :size="13" /> Prochaine échéance</dt><dd>{{ agenda.prochains[0] ? `${tid(agenda.prochains[0].id)} · ${fmtDate(agenda.prochains[0].echeance)}` : 'Aucune' }}</dd></div>
          <div :class="agenda.retards > 0 && 'is-alert'"><dt><Icon name="alert" :size="13" /> Déjà en retard</dt><dd>{{ agenda.retards }} ticket{{ agenda.retards > 1 ? 's' : '' }}</dd></div>
        </dl>
      </section>

      <!-- Charge par membre : matrice membre × statut (diagramme de la version 34), voisine du bloc principal -->
      <section class="nx-card nx-card-p nx-s5 nx-in" style="--i: 2">
        <header class="nx-card-h"><span class="nx-ico"><Icon name="users" :size="17" /></span><div><h2>Charge par membre</h2><p>Tickets non terminés, par membre et par statut</p></div></header>
        <div v-if="charge.length">
          <table class="nx-heat" aria-label="Charge par membre et par statut">
            <colgroup><col style="width: 8.4rem"><col v-for="k in COLS_CHARGE" :key="k.k"><col style="width: 4.8rem"></colgroup>
            <thead><tr><th /><th v-for="k in COLS_CHARGE" :key="k.k" scope="col" :class="k.k === 'retard' && 'late'">{{ ABREGE[k.k] }}</th><th scope="col">Charge</th></tr></thead>
            <tbody>
              <tr v-for="c in charge" :key="c.id" :class="membreF === c.id && 'is-on'" :title="`${c.nom} : ${c.n} ticket(s) non terminé(s) · cliquer pour filtrer le tableau`" @click="membreF = membreF === c.id ? null : c.id">
                <th scope="row"><span class="who"><Avatar :nom="c.nom" :src="c.photo" :size="26" /><span>{{ c.nom }}</span></span></th>
                <td v-for="k in COLS_CHARGE" :key="k.k" class="c" :class="c.par[k.k] ? ['v', k.k === 'retard' && 'late', fort(c.par[k.k] ?? 0) && 'fort'] : 'z'" :style="c.par[k.k] ? intensite(c.par[k.k] ?? 0) : undefined">{{ c.par[k.k] || '·' }}</td>
                <td><span class="badge" :class="c.niv.cls">{{ c.niv.l }}</span></td>
              </tr>
            </tbody>
          </table>
          <p class="nx-heat-note"><i />plus la case est foncée, plus la charge est forte · cliquer sur un membre filtre le tableau</p>
        </div>
        <p v-else class="text-sm text-slate-500">Aucun ticket affecté.</p>
      </section>

      <!-- NIVEAU 2 · les échéances : frise ou avancement (onglets), et la liste des prochaines -->
      <h2 v-if="total" class="nx-niveau nx-s12"><span>2</span>Échéances<small>Ce qui arrive et où en sont les tickets</small></h2>
      <section v-if="total" class="nx-card nx-card-p nx-s7 nx-in" style="--i: 3">
        <header class="nx-card-h">
          <span class="nx-ico"><Icon :name="onglet === 'frise' ? 'calendar' : 'trending'" :size="17" /></span>
          <div><h2>{{ onglet === 'frise' ? 'Frise des 14 prochains jours' : 'Avancement déclaré' }}</h2>
            <p>{{ onglet === 'frise' ? 'Une pastille = un ticket non terminé · cliquer pour ouvrir' : 'Tickets non terminés, du plus avancé au moins avancé' }}</p></div>
          <div class="nx-tabs ml-auto" role="tablist" aria-label="Type de vue">
            <button type="button" role="tab" class="nx-tab" :aria-selected="onglet === 'frise'" @click="onglet = 'frise'">Échéances <b>{{ frise.total }}</b></button>
            <button type="button" role="tab" class="nx-tab" :aria-selected="onglet === 'avancement'" @click="onglet = 'avancement'">Avancement</button>
          </div>
        </header>
        <div v-if="onglet === 'frise'" class="nx-frise" role="group" aria-label="Frise des échéances">
          <div class="nx-fr-col is-late"><div class="nx-fr-pile"><button v-for="r in frise.retards" :key="r.id" type="button" class="nx-pin is-late" :title="`${tid(r.id)} · ${r.titre} (en retard)`" @click="router.push(`/tickets/${r.id}`)">{{ tid(r.id).replace('T-', '') }}</button></div>
            <span class="nx-fr-lab nx-fr-lab-late">RETARD</span></div>
          <div v-for="(c, i) in frise.cols" :key="i" class="nx-fr-col" :class="[i === 0 && 'is-today', c.we && 'is-we']">
            <div class="nx-fr-pile"><button v-for="r in c.items" :key="r.id" type="button" class="nx-pin" :class="r.situation === 'a_surveiller' && 'is-watch'" :title="`${tid(r.id)} · ${r.titre}`" @click="router.push(`/tickets/${r.id}`)">{{ tid(r.id).replace('T-', '') }}</button></div>
            <span class="nx-fr-lab">{{ i === 0 ? 'AUJ.' : lettre(c.d) }}<em>{{ c.d.getDate() }}</em></span>
          </div>
        </div>
        <ul v-else-if="avancements.length" class="nx-av">
          <li v-for="a in avancements" :key="a.label"><span class="truncate" :title="a.label">{{ a.label }}</span><b>{{ a.value }} %</b>
            <div class="nx-av-t"><i :style="{ width: a.value + '%', background: a.color }" /></div></li>
        </ul>
        <p v-else class="text-sm text-slate-500">Aucun ticket en cours.</p>
      </section>

      <section v-if="total" class="nx-card nx-card-p nx-s5 nx-in" style="--i: 4">
        <header class="nx-card-h"><span class="nx-ico"><Icon name="clock" :size="17" /></span><div><h2>Prochaines échéances</h2><p>{{ agenda.retards ? `${agenda.retards} ticket(s) déjà en retard · ` : '' }}tickets non terminés</p></div></header>
        <div v-if="agenda.prochains.length" class="nx-next">
          <button v-for="r in agenda.prochains" :key="r.id" type="button" @click="router.push(`/tickets/${r.id}`)">
            <span class="d"><b>{{ jourNum(r.echeance) }}</b><small>{{ mois(r.echeance) }}</small></span>
            <span class="t">{{ r.titre }}<small>{{ tid(r.id) }} · {{ r.etat_echeance }}</small></span>
            <Icon name="right" :size="15" class="text-slate-300" />
          </button>
        </div>
        <p v-else class="text-sm text-slate-500">Aucune échéance à venir.</p>
      </section>

      <!-- Liste des tickets -->
      <h2 class="nx-niveau nx-s12"><span>3</span>Tickets<small>Recherche, filtres et accès au détail</small></h2>
      <section class="nx-card nx-s12 nx-in" style="--i: 5" aria-label="Liste des tickets">
        <div class="nx-liste-bar">
          <h2 class="mr-2 flex items-center gap-2 font-semibold" style="font-family: var(--font-display)">Liste des tickets <span class="nx-count">{{ d ? shown.length : 0 }}</span></h2>
          <div class="relative ml-auto w-full sm:w-72">
            <Icon name="search" :size="15" class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input v-model="q" class="input pl-9" placeholder="Rechercher un ticket" aria-label="Rechercher un ticket" />
          </div>
          <div class="nx-filtres">
            <button v-for="f in FILTRES" :key="f.k" type="button" class="nx-chip" :class="filtre === f.k && 'is-on'" :aria-pressed="filtre === f.k" @click="filtre = f.k">{{ f.l }} <i>{{ count(f.k) }}</i></button>
            <button v-if="filtreActif" type="button" class="nx-reset" @click="reinitialiser"><Icon name="x" :size="12" /> Réinitialiser</button>
          </div>
        </div>
        <p v-if="membreF !== null" class="flex items-center gap-2 px-5 pt-3 text-xs text-slate-500">Filtré sur<button type="button" class="nx-chip is-on !py-0.5" @click="membreF = null">{{ filtreNom }} ✕</button></p>
        <div class="overflow-x-auto">
          <table class="nx-table min-w-[60rem]">
            <thead>
              <tr>
                <th v-for="c in COLS" :key="c.k" :aria-sort="ariaSort(c.k)"><button @click="trier(c.k)">{{ c.l }} {{ fleche(c.k) }}</button></th>
                <th class="c-act" aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in shown" :key="r.id" tabindex="0" role="link" @click="router.push(`/tickets/${r.id}`)" @keyup.enter="router.push(`/tickets/${r.id}`)">
                <td>
                  <div class="flex items-center">
                    <span class="nx-row-bar" :style="{ background: accentLigne(r) }" />
                    <div class="mr-3 flex w-14 shrink-0 -space-x-1">
                      <Avatar v-for="m in equipe(r).slice(0, 2)" :key="m.id" :nom="m.nom" :src="photoCrm(m.photo)" :size="30" ring calm />
                      <span v-if="!equipe(r).length" class="grid size-[30px] place-items-center rounded-full border border-dashed border-slate-300 text-slate-300"><Icon name="user" :size="13" /></span>
                    </div>
                    <div class="min-w-0">
                      <p class="max-w-md truncate text-sm font-semibold" :title="r.titre">{{ r.titre }}</p>
                      <p class="mt-0.5 text-xs font-medium text-slate-400">{{ tid(r.id) }}</p>
                    </div>
                  </div>
                </td>
                <td><StatutBadge :statut="r.statut" calm /><p v-if="r.cloture_a_valider" class="nx-cloture-flag"><Icon name="check" :size="11" /> Clôture à valider</p></td>
                <td>
                  <p class="text-sm" :class="r.situation === 'en_retard' ? 'font-semibold text-[color:var(--nx-late)]' : 'text-slate-700'">{{ r.etat_echeance }}</p>
                  <p class="mt-0.5 text-xs text-slate-400">Échéance {{ fmtDate(r.echeance) }}</p>
                </td>
                <td><div class="nx-prog"><span><i :style="{ width: r.avancement_declare + '%' }" :class="r.situation === 'en_retard' && 'late'" /></span><b>{{ r.avancement_declare }} %</b></div></td>
                <td class="text-right"><RouterLink :to="`/tickets/${r.id}`" class="nx-go" :aria-label="`Détails de ${r.titre}`" @click.stop>Détails <Icon name="right" :size="13" /></RouterLink></td>
              </tr>
            </tbody>
          </table>
        </div>
        <EmptyState v-if="d && !shown.length" icon="search" title="Aucun ticket" text="Aucun ticket ne correspond à ces filtres." />
        <p v-if="!d && !err" class="p-6 text-center text-sm text-slate-500">Chargement…</p>
      </section>
    </div>
  </div>
</template>
