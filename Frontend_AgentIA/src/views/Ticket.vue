<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { api, fmtDate, photoCrm, post, put, RISQUE, STATUT, tid } from '@/services/api'
import { usePolling } from '@/composables/usePolling'
import { useProjectStore } from '@/stores/project'
import { useToastStore } from '@/stores/toast'
import Avatar from '@/components/Avatar.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'
import Icon from '@/components/Icon.vue'
import SituationBadge from '@/components/SituationBadge.vue'
import StatutBadge from '@/components/StatutBadge.vue'

const id = Number(useRoute().params.id)
const toast = useToastStore()
const project = useProjectStore()
const d = ref<any>(null), err = ref(''), syn = ref<any>(null)
const nouvelle = ref(''), motif = ref(''), confirm = ref(false), busy = ref(false)
const confirmCloture = ref(false), busyCloture = ref(false)
const criteres = computed<string[]>(() => d.value?.criteres_acceptation ?? [])
const valides = computed<boolean[]>(() => d.value?.criteres_valides ?? [])
const nbValides = computed(() => valides.value.filter(Boolean).length)
/** Section de clôture visible UNIQUEMENT si l'avancement CRM est à 100 % ET tous les critères sont cochés (règle vérifiée aussi par le serveur). */
const aCloturer = computed(() => !!d.value?.cloturable)
const busyCritere = ref(false)
async function cocher(i: number, valide: boolean) {
  if (busyCritere.value || d.value?.ticket?.statut === 'ferme') return
  busyCritere.value = true
  try { await put(`/tickets/${id}/criteres/${i}/validation`, { valide }); await load() } catch (e: any) { toast.err(e.message) }
  busyCritere.value = false
}
/** Clôture : décision du haut responsable, jamais automatique (le taux d'avancement et le statut sont indépendants). */
async function cloturer() {
  busyCloture.value = true
  try {
    await post(`/tickets/${id}/cloture`)
    toast.ok('Clôture validée : le ticket est fermé.')
    confirmCloture.value = false
    await load()
  } catch (e: any) { toast.err(e.message); confirmCloture.value = false }
  busyCloture.value = false
}

async function load() {
  try { d.value = await api(`/tickets/${id}/analyse`); err.value = '' } catch (e: any) { err.value = e.message }
  // La synthèse du projet : sert uniquement à savoir si l'agent a quelque chose à dire sur cette tâche (cloche)
  if (project.activeId) { try { syn.value = await api(`/projets/${project.activeId}/synthese`) } catch { /* facultatif */ } }
}
/** Date du jour (heure locale) au format AAAA-MM-JJ : aucune échéance antérieure ne peut être choisie. */
const aujourdhui = (() => { const n = new Date(); return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, '0')}-${String(n.getDate()).padStart(2, '0')}` })()
async function changeEcheance() {
  if (nouvelle.value && nouvelle.value < aujourdhui) { toast.err("La nouvelle échéance ne peut pas être antérieure à aujourd'hui."); confirm.value = false; return }
  busy.value = true
  try {
    await put(`/tickets/${id}/echeance`, { nouvelle_date: nouvelle.value, motif: motif.value })
    toast.ok('Échéance modifiée et inscrite au journal.')
    nouvelle.value = motif.value = ''
    confirm.value = false
    await load()                      // la nouvelle échéance est déjà prise en compte par le serveur : affichage immédiat
    setTimeout(load, 2500)            // puis affinage de l'IA
  } catch (e: any) { toast.err(e.message); confirm.value = false }
  busy.value = false
}
usePolling(load, 5000)   // la page suit les événements CRM et le passage du temps

// Chronologie unique : statuts, motifs (attente / retard) et avancements déclarés
const chrono = computed(() => {
  if (!d.value) return []
  const ev: any[] = []
  for (const h of d.value.historique.statuts) ev.push({ date: h.date, kind: h.type_motif ?? 'statut', h })
  for (const a of d.value.historique.avancements) ev.push({ date: a.date, kind: 'avancement', a })
  return ev.sort((x, y) => +new Date(y.date) - +new Date(x.date))
})
const nbAttentes = computed(() => d.value?.historique.statuts.filter((h: any) => h.type_motif === 'attente').length ?? 0)

/** Cloche : ce que la synthèse de l'agent contient sur CETTE tâche (recommandation, priorité, risque / prédiction). */
const signaux = computed(() => {
  const l: string[] = []
  const nbReco = (syn.value?.recommandations ?? []).filter((r: any) => r.id_ticket === id).length || (d.value?.recommandations ?? []).filter((r: any) => !r.decision).length
  if (nbReco) l.push(`${nbReco} recommandation${nbReco > 1 ? 's' : ''} à décider`)
  const p = (syn.value?.synthese?.priorites ?? []).find((x: any) => x.id === id)
  if (p) l.push(`Priorité n° ${p.rang ?? ''}`.trim() + (p.raisons?.[0] ? ` · ${p.raisons[0]}` : ''))
  const r = (syn.value?.synthese?.risques ?? []).find((x: any) => x.id === id)
  if (r) l.push(`Prédiction : risque ${r.risque === 'eleve' ? 'élevé' : 'modéré'}`)
  return l
})
const paragraphes = computed(() => String(d.value?.ticket?.description ?? '').split(/\n+/).map((p: string) => p.trim()).filter(Boolean))
const ACCENT: Record<string, string> = { en_retard: '#FF5A36', a_surveiller: '#F2A93B', ferme: '#94A3BA' }
const accent = computed(() => ACCENT[d.value?.calculs?.situation] ?? '#0A182C')
const a = computed(() => d.value?.analyse)
const KIND: Record<string, { bg: string; ico: string; lib: string }> = {
  statut: { bg: '#0A182C', ico: 'check', lib: 'Statut' },
  avancement: { bg: '#6A83A9', ico: 'activity', lib: 'Avancement' },
  attente: { bg: '#F2A93B', ico: 'clock', lib: 'Mise en attente' },
  retard: { bg: '#FF5A36', ico: 'alert', lib: 'Retard' },
}
const FILTRES = [
  { k: 'tout', l: 'Tout', vide: 'Aucun événement enregistré.' },
  { k: 'statut', l: 'Statuts', vide: "Aucun changement de statut enregistré." },
  { k: 'avancement', l: 'Avancements', vide: "Aucune mise à jour d'avancement enregistrée." },
  { k: 'attente', l: 'Mises en attente', vide: "Ce ticket n'a jamais été mis en attente." },
  { k: 'retard', l: 'Retards', vide: "Aucun motif de retard n'a été renseigné pour ce ticket." },
]
const filtre = ref('tout')
const recentD = ref(true)          // tri : du plus récent au plus ancien (ou l'inverse)
const garde = (e: any, k: string) => k === 'tout' || e.kind === k
const vus = computed(() => { const l = chrono.value.filter((e) => garde(e, filtre.value)); return recentD.value ? l : [...l].reverse() })
const nb = (k: string) => chrono.value.filter((e) => garde(e, k)).length
const videMsg = computed(() => FILTRES.find((f) => f.k === filtre.value)?.vide ?? '')
const jourLabel = (iso: string) => {
  const j = new Date(iso); j.setHours(0, 0, 0, 0)
  const t = new Date(); t.setHours(0, 0, 0, 0)
  const diff = Math.round((+t - +j) / 86400000)
  return diff === 0 ? "Aujourd'hui" : diff === 1 ? 'Hier' : fmtDate(iso)
}
const jourSous = (iso: string) => new Date(iso).toLocaleDateString('fr-FR', { weekday: 'long' })
const groupes = computed(() => {
  const m = new Map<string, { label: string; sous: string; items: any[] }>()
  for (const e of vus.value) {
    const k = String(e.date).slice(0, 10)
    if (!m.has(k)) m.set(k, { label: jourLabel(e.date), sous: jourSous(e.date), items: [] })
    m.get(k)!.items.push(e)
  }
  return [...m.values()]
})
const heure = (iso: string) => new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
const ETAPES = [{ k: 'nouveau', l: 'Nouveau' }, { k: 'ouvert', l: 'Ouvert' }, { k: 'en_cours', l: 'En cours' }, { k: 'ferme', l: 'Fermé' }]
const etapeCourante = computed(() => { const st = d.value?.ticket.statut; const i = ETAPES.findIndex((x) => x.k === (st === 'en_attente' ? 'en_cours' : st)); return i < 0 ? 0 : i })
const enAttente = computed(() => d.value?.ticket.statut === 'en_attente')
const dateEtape = (k: string) => {
  const h = d.value?.historique.statuts.filter((x: any) => x.statut === k && !x.type_motif).sort((x: any, y: any) => +new Date(x.date) - +new Date(y.date))[0]
  return h ? fmtDate(h.date) : ''
}
</script>

<template>
  <div class="nx mx-auto w-full">
    <nav class="nx-crumb" aria-label="Fil d'Ariane"><RouterLink to="/tableau"><Icon name="left" :size="15" /> Tableau de bord</RouterLink><span aria-hidden="true">/</span><span class="font-semibold text-slate-900">Détails sur la tâche</span></nav>

    <div v-if="err" class="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800" role="alert">
      <Icon name="alert" :size="16" /><span class="flex-1">{{ err }}</span>
      <button class="btn-secondary btn-sm" @click="load">Réessayer</button>
    </div>

    <template v-if="d">
      <!-- CARTE PRINCIPALE : identité, cycle de vie, « Situation » (explication de l'agent) et faits clés -->
      <header class="nx-card nx-main nx-in" :style="{ '--accent': accent }">
        <div class="flex flex-wrap items-start justify-between gap-6">
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
              <span class="nx-tk-id">{{ tid(id) }}</span>
              <StatutBadge :statut="d.ticket.statut" />
              <SituationBadge :situation="d.calculs.situation" :label="d.calculs.libelle" />
              <span v-if="a" :class="RISQUE[a.risque]?.cls ?? 'badge-slate'">{{ RISQUE[a.risque]?.label ?? a.risque }}</span>
            </div>
            <h1 class="nx-tk-titre">{{ d.ticket.titre }}</h1>
          </div>
          <div class="flex items-center gap-4">
            <!-- Cloche : visible seulement si la synthèse de l'agent contient une recommandation, une priorité ou une prédiction sur cette tâche -->
            <div v-if="signaux.length" class="nx-bell-wrap">
              <RouterLink to="/situation" class="nx-bell is-on" :aria-label="`L'agent a ${signaux.length} signal${signaux.length > 1 ? 'aux' : ''} sur cette tâche : ouvrir la synthèse`">
                <Icon name="bell" :size="20" /><sup>{{ signaux.length }}</sup>
              </RouterLink>
              <div class="nx-bell-tip" role="tooltip"><b>Dans la synthèse de l'agent</b><ul><li v-for="s in signaux" :key="s">{{ s }}</li></ul></div>
            </div>
            <div class="nx-ring">
              <svg viewBox="0 0 80 80" class="size-24 -rotate-90" role="img" :aria-label="`Avancement ${d.ticket.avancement_declare} %`">
                <circle cx="40" cy="40" r="32" fill="none" stroke="#EBEFF4" stroke-width="7" />
                <circle cx="40" cy="40" r="32" fill="none" stroke="var(--accent)" stroke-width="7" stroke-linecap="round"
                  :stroke-dasharray="201" :stroke-dashoffset="201 - (201 * d.ticket.avancement_declare) / 100" style="transition: stroke-dashoffset 900ms ease" />
              </svg>
              <b>{{ d.ticket.avancement_declare }}<small>%</small></b>
            </div>
          </div>
        </div>

        <ol class="nx-rail" aria-label="Cycle de vie du ticket">
          <li v-for="(e, i) in ETAPES" :key="e.k" :class="[i < etapeCourante || (i === etapeCourante && d.ticket.statut === 'ferme') ? 'is-fait' : i === etapeCourante ? 'is-courant' : '', i === etapeCourante && enAttente && 'is-attente']">
            <span class="nx-rail-pt"><Icon v-if="i < etapeCourante || (i === etapeCourante && d.ticket.statut === 'ferme')" name="check" :size="12" /><Icon v-else-if="i === etapeCourante && enAttente" name="clock" :size="12" /><template v-else>{{ i + 1 }}</template></span>
            <span class="nx-rail-l">{{ i === etapeCourante && enAttente ? 'En attente' : e.l }}</span><span class="nx-rail-d">{{ dateEtape(e.k) }}</span>
          </li>
        </ol>

        <!-- Situation : l'explication de l'agent au responsable, intégrée à la carte principale -->
        <div v-if="a?.analyse" class="nx-situation">
          <p class="nx-situation-h"><Icon name="activity" :size="14" /> Situation</p>
          <p>{{ a.analyse }}</p>
        </div>

        <dl class="nx-faits">
          <div><dt><Icon name="clock" :size="14" /> Échéance</dt><dd>{{ fmtDate(d.ticket.echeance) }}<small>{{ d.calculs.libelle }}</small></dd></div>
          <div><dt><Icon name="user" :size="14" /> Membres</dt>
            <dd v-if="d.membres.length" class="flex items-center gap-2.5"><span class="flex -space-x-2"><Avatar v-for="m in d.membres" :key="m.id" :nom="m.nom" :src="photoCrm(m.photo)" :size="28" ring /></span><span class="truncate">{{ d.membres.map((m: any) => m.nom).join(', ') }}</span></dd>
            <dd v-else class="text-slate-400">Aucun membre rattaché</dd></div>
          <div><dt><Icon name="link" :size="14" /> Dépend de</dt>
            <dd class="flex flex-wrap gap-1.5"><template v-if="d.depend_de.length"><RouterLink v-for="x in d.depend_de" :key="x.id" :to="`/tickets/${x.id}`" class="badge-slate transition hover:bg-white">{{ tid(x.id) }}</RouterLink></template><span v-else class="font-normal text-slate-400">Aucune dépendance</span></dd></div>
          <div><dt><Icon name="alert" :size="14" /> Bloque</dt>
            <dd class="flex flex-wrap gap-1.5"><template v-if="d.bloque.length"><RouterLink v-for="x in d.bloque" :key="x.id" :to="`/tickets/${x.id}`" class="badge-amber transition hover:brightness-95">{{ tid(x.id) }}</RouterLink></template><span v-else class="font-normal text-slate-400">Aucune tâche bloquée</span></dd></div>
        </dl>
      </header>

      <!-- CLÔTURE : visible seulement à 100 % d'avancement (CRM) avec tous les critères d'acceptation cochés ; décision humaine -->
      <section v-if="aCloturer" class="nx-card nx-card-p nx-in nx-card-cloture" style="--i: 1" aria-labelledby="t-clo">
        <div class="nx-cloture-corps">
          <div class="flex items-start gap-3">
            <span class="nx-ico"><Icon name="check" :size="17" /></span>
            <div>
              <h2 id="t-clo" class="font-semibold" style="font-family: var(--font-display); font-size: 1.0625rem">Clôturer la tâche</h2>
              <p class="text-[13px] text-slate-500">L'avancement est de 100 % et les {{ criteres.length }} critères d'acceptation sont validés. Le ticket garde son statut « {{ STATUT[d.ticket.statut] }} » tant que vous n'avez pas validé sa clôture.</p>
            </div>
          </div>
          <button class="btn-primary" @click="confirmCloture = true">Clôturer la tâche</button>
        </div>
      </section>

      <!-- CRITÈRES D'ACCEPTATION -->
      <section class="nx-card nx-card-p nx-in" style="--i: 1" aria-labelledby="t-crit">
        <header class="nx-card-h"><span class="nx-ico"><Icon name="check" :size="17" /></span>
          <div><h2 id="t-crit">Critères d'acceptation</h2><p>Conditions vérifiables à remplir pour considérer la tâche comme terminée</p></div>
          <span class="nx-count" :title="nbValides + ' critère(s) validé(s) sur ' + criteres.length">{{ nbValides }}/{{ criteres.length }}</span></header>
        <ol class="nx-criteres">
          <li v-for="(c, i) in criteres" :key="i">
            <label class="nx-crit-ligne" :class="valides[i] && 'nx-crit-ok'">
              <input type="checkbox" class="nx-crit-case" :checked="valides[i]" :disabled="busyCritere || d.ticket.statut === 'ferme'"
                :aria-label="'Critère ' + (i + 1) + ' validé'" @change="cocher(i, ($event.target as HTMLInputElement).checked)" />
              <span class="nx-crit-n">{{ i + 1 }}</span><p>{{ c }}</p>
            </label>
          </li>
        </ol>
        <p v-if="d.criteres_par_defaut" class="nx-crit-source">Critères proposés par défaut à partir de l'énoncé de la tâche.</p>
        <p v-if="d.critere_source" class="nx-crit-source">Source dans le cahier des charges : « {{ d.critere_source }} »</p>
      </section>

      <!-- DESCRIPTION et MODIFICATION côte à côte -->
      <div class="nx-duo">
        <section class="nx-card nx-card-p nx-in" style="--i: 1" aria-labelledby="t-desc">
          <header class="nx-card-h"><span class="nx-ico"><Icon name="file" :size="17" /></span><div><h2 id="t-desc">Description de la tâche</h2><p>Ce qui est attendu pour cette tâche</p></div></header>
          <div v-if="paragraphes.length" class="nx-desc">
            <p v-for="(p, i) in paragraphes" :key="i" :class="i === 0 && 'lead'">{{ p }}</p>
          </div>
          <p v-else class="nx-vide">Aucune description renseignée pour cette tâche.</p>
          <footer class="nx-desc-pied">
            <span><Icon name="clock" :size="13" /> Échéance {{ fmtDate(d.ticket.echeance) }}</span>
            <span><Icon name="user" :size="13" /> {{ d.membres.length }} membre{{ d.membres.length > 1 ? 's' : '' }}</span>
            <span><Icon name="link" :size="13" /> {{ d.depend_de.length }} dépendance{{ d.depend_de.length > 1 ? 's' : '' }}</span>
            <span><Icon name="alert" :size="13" /> bloque {{ d.bloque.length }} tâche{{ d.bloque.length > 1 ? 's' : '' }}</span>
          </footer>
        </section>

        <section class="nx-card nx-card-p nx-in" style="--i: 2" aria-labelledby="t-mod">
          <header class="nx-card-h"><span class="nx-ico"><Icon name="edit" :size="17" /></span><div><h2 id="t-mod">Modifier la tâche</h2><p>Le changement d'échéance est inscrit au journal</p></div></header>
          <div class="nx-actuelle">
            <div><p class="nx-eyebrow">Échéance actuelle</p><p class="nx-num mt-1">{{ fmtDate(d.ticket.echeance) }}</p></div>
            <SituationBadge :situation="d.calculs.situation" :label="d.calculs.libelle" />
          </div>
          <fieldset :disabled="d.ticket.statut === 'ferme'" class="mt-5 grid gap-4 disabled:opacity-60">
            <div class="nx-field"><label for="ech">Nouvelle date</label><input id="ech" v-model="nouvelle" type="date" class="input" :min="aujourdhui" /></div>
            <div class="nx-field"><label for="mot">Motif <span class="font-normal text-slate-400">(obligatoire)</span></label>
              <input id="mot" v-model="motif" class="input" placeholder="Ex. dépendance externe non livrée" /></div>
            <button class="btn-primary w-full" :disabled="!nouvelle || nouvelle < aujourdhui || motif.trim().length < 3" @click="confirm = true">Modifier l'échéance</button>
            <p v-if="nouvelle && nouvelle < aujourdhui" class="-mt-2 text-xs text-red-700" role="alert">Choisissez une date à partir d'aujourd'hui.</p>
          </fieldset>
          <p v-if="d.ticket.statut === 'ferme'" class="mt-3 flex items-center gap-1.5 text-xs text-slate-500"><Icon name="lock" :size="12" /> Ticket fermé : l'échéance n'est plus modifiable.</p>
        </section>
      </div>

      <!-- CHRONOLOGIE : une seule grande carte, sur toute la largeur -->
      <section class="nx-card nx-chrono nx-in" style="--i: 3" aria-label="Chronologie du ticket">
        <header class="nx-chrono-h">
          <span class="nx-ico"><Icon name="history" :size="17" /></span>
          <div><h2 class="font-semibold" style="font-family: var(--font-display); font-size: 1.0625rem">Chronologie du ticket</h2><p class="text-[13px] text-slate-500">Statuts, avancements, mises en attente et retards : filtrez par type</p></div>
          <span class="nx-count !ml-1">{{ chrono.length }}</span>
          <span v-if="nbAttentes" class="badge-amber">{{ nbAttentes }} mise{{ nbAttentes > 1 ? 's' : '' }} en attente</span>
          <div class="nx-tabs ml-auto" role="tablist" aria-label="Filtrer la chronologie">
            <button v-for="f in FILTRES" :key="f.k" type="button" role="tab" class="nx-tab" :aria-selected="filtre === f.k" @click="filtre = f.k">{{ f.l }}<b>{{ nb(f.k) }}</b></button>
            <button type="button" class="nx-tab" :title="recentD ? 'Du plus récent au plus ancien' : 'Du plus ancien au plus récent'" @click="recentD = !recentD">{{ recentD ? '↓ Récent' : '↑ Ancien' }}</button>
          </div>
        </header>
        <div class="nx-chrono-b">
          <template v-if="groupes.length">
            <div v-for="g in groupes" :key="g.label" class="nx-jour">
              <p class="nx-jour-l"><b>{{ g.label }}</b><span style="text-transform: capitalize; letter-spacing: 0; font-weight: 500">{{ g.sous }}</span></p>
              <ol class="nx-ev-liste">
                <li v-for="(e, i) in g.items" :key="g.label + i" class="nx-ev">
                  <span class="nx-ev-dot" :style="{ background: KIND[e.kind]!.bg }"><Icon :name="KIND[e.kind]!.ico" :size="16" /></span>
                  <div class="min-w-0">
                    <div class="nx-ev-top"><span>{{ KIND[e.kind]!.lib }}</span><time>{{ heure(e.date) }}</time></div>
                    <p v-if="e.kind === 'statut'">Passage à <b>{{ STATUT[e.h.statut] ?? e.h.statut }}</b></p>
                    <template v-else-if="e.kind === 'avancement'">
                      <p>Avancement déclaré : <b>{{ e.a.ancienne }} %</b> → <b>{{ e.a.nouvelle }} %</b></p>
                      <div class="nx-ev-bar"><i :style="{ width: e.a.nouvelle + '%' }" /></div>
                    </template>
                    <template v-else>
                      <p><b>{{ e.kind === 'attente' ? "Motif d'attente" : 'Motif de retard' }}</b> · {{ e.h.motif }}</p>
                      <p v-if="e.h.date_resolution" class="!mt-1 text-xs text-slate-400">Archivé le {{ fmtDate(e.h.date_resolution) }}</p>
                      <p v-else class="!mt-1.5 inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700"><Icon name="lock" :size="11" /> En cours (verrouillé)</p>
                    </template>
                  </div>
                </li>
              </ol>
            </div>
          </template>
          <div v-else class="py-10 text-center text-sm text-slate-500">
            <p>{{ videMsg }}</p>
            <button v-if="filtre !== 'tout' && chrono.length" type="button" class="btn-secondary btn-sm mt-3" @click="filtre = 'tout'">Afficher tous les événements ({{ chrono.length }})</button>
          </div>
        </div>
      </section>

      <ConfirmModal :open="confirmCloture" title="Valider la clôture du ticket" confirm-label="Clôturer" :busy="busyCloture" @confirm="cloturer" @cancel="confirmCloture = false">
        <p><b>{{ tid(id) }}</b> passera au statut « Fermé » (avancement déclaré : {{ d.ticket.avancement_declare }} %).</p>
        <p v-if="d.ticket.avancement_declare < 100" class="mt-1 text-amber-700">L'avancement déclaré n'est pas à 100 % : confirmez que le travail est bien terminé.</p>
        <p class="mt-1">Cette décision est inscrite au journal.</p>
      </ConfirmModal>

      <ConfirmModal :open="confirm" title="Confirmer le changement d'échéance" confirm-label="Modifier" :busy="busy" @confirm="changeEcheance" @cancel="confirm = false">
        <p>L'échéance de <b>{{ tid(id) }}</b> passera du <b>{{ fmtDate(d.ticket.echeance) }}</b> au <b>{{ fmtDate(nouvelle) }}</b>.</p>
        <p class="mt-1">Motif : « {{ motif }} ».</p>
      </ConfirmModal>
    </template>

    <div v-else-if="!err" class="space-y-4" role="status" aria-live="polite" aria-label="Chargement du ticket">
      <div class="nx-skel" style="height: 22rem" /><div class="grid gap-4 md:grid-cols-2"><div class="nx-skel" style="height: 16rem" /><div class="nx-skel" style="height: 16rem" /></div>
    </div>
  </div>
</template>
