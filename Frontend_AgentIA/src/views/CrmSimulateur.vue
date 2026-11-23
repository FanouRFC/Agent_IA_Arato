<script setup lang="ts">
import { useConfirmStore } from '@/stores/confirm'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { crmApi, fmtDate, fmtDateTime, photoCrm, STATUT, tid } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'
import Avatar from '@/components/Avatar.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'
import Icon from '@/components/Icon.vue'
import Modal from '@/components/Modal.vue'
import ProgressBar from '@/components/ProgressBar.vue'
import StatutBadge from '@/components/StatutBadge.vue'
import ToastHost from '@/components/ToastHost.vue'

/* Simulateur de l'espace CRM : les membres y créent et modifient tickets, projets et membres, changent statut,
   avancement déclaré et motifs. Échéance et est_en_retard restent en lecture seule après la création. */
const confirmer = useConfirmStore()
const toast = useToastStore()
const auth = useAuthStore()
const projets = ref<any[]>([]), membres = ref<any[]>([]), tickets = ref<any[]>([]), tous = ref<any[]>([])
const projetId = ref<number | ''>(''), statutF = ref(''), q = ref(''), sel = ref<any>(null), hist = ref<any>(null)
const auteur = ref<number | null>(null), categorie = ref(''), motif = ref(''), motifRetard = ref('')
const modal = ref<'' | 'ticket' | 'projet' | 'membre' | 'membres' | 'suppr_membre' | 'projets' | 'suppr_projet' | 'suppression' | 'attente'>('')
const editing = ref(false)   // le formulaire de modification s'affiche dans la fenêtre du ticket
const busy = ref(false), selStatut = ref<HTMLSelectElement>()
const nouveau = ref({ titre: '', description: '', projet_id: '' as number | '', echeance: '', membre_ids: [] as number[], depend_de_ids: [] as number[] })
const nvProjet = ref('')
// Gestion des membres : création et modification (avec photo), suppression sécurisée
const nvMembre = ref<{ id: number | null; nom: string; profil: string; email: string; fichier: File | null; apercu: string | null; photoActuelle: string | null }>(
  { id: null, nom: '', profil: '', email: '', fichier: null, apercu: null, photoActuelle: null })
const membreASupprimer = ref<any>(null)
const MOTIFS = ["attente d'une information", "attente d'une validation", 'problème technique', 'dépendance non terminée', 'information manquante', 'autre']
const nomMembre = (id: number) => membres.value.find((m) => m.id === id)?.nom ?? '?'
const nomProjet = (id: number) => projets.value.find((p) => p.id === id)?.nom ?? '—'
const send = (method: string, path: string, body?: unknown) =>
  crmApi(path, { method, ...(body === undefined ? {} : { body: JSON.stringify(body) }) })
const basculer = (arr: number[], id: number) => { const i = arr.indexOf(id); i >= 0 ? arr.splice(i, 1) : arr.push(id) }
const chip = (actif: boolean) => ['chip', actif ? 'chip-on' : 'chip-off']

async function load() {
  try {
    ;[projets.value, membres.value] = await Promise.all([crmApi('/projets'), crmApi('/membres')])
    await loadTickets()
  } catch (e: any) { toast.err(e.message) }
}
async function rechargerReferentiels() {
  ;[projets.value, membres.value] = await Promise.all([crmApi('/projets'), crmApi('/membres')])
}
async function ouvrirMembres() {
  modal.value = 'membres'
  try { await rechargerReferentiels() } catch (e: any) { toast.err(e.message) }
}
async function loadTickets() {
  const qs = new URLSearchParams()
  if (projetId.value) qs.set('projet_id', String(projetId.value))
  if (statutF.value) qs.set('statut', statutF.value)
  ;[tickets.value, tous.value] = await Promise.all([crmApi('/tickets?' + qs), crmApi('/tickets')])
  if (sel.value) await choisir(tickets.value.find((t) => t.id === sel.value.id) ?? null)
}
async function choisir(t: any) {
  const meme = t && sel.value?.id === t.id
  sel.value = t; if (!meme) hist.value = null; if (!meme) { motifRetard.value = ''; editing.value = false }
  if (!t) return
  auteur.value = auteur.value && t.membre_ids.includes(auteur.value) ? auteur.value : (t.membre_ids[0] ?? null)
  try { hist.value = await crmApi(`/tickets/${t.id}/historique`) } catch { /* facultatif */ }
}
// Mise à jour automatique : les projets, membres et tickets se rafraîchissent seuls (aucun rechargement manuel)
let sync: number | undefined
async function synchroniser() {
  if (document.hidden || modal.value || editing.value) return
  try { await rechargerReferentiels(); await loadTickets() } catch { /* silencieux : le prochain passage réessaie */ }
}
onMounted(() => { load(); sync = window.setInterval(synchroniser, 3000) })
onUnmounted(() => window.clearInterval(sync))
watch([projetId, statutF], loadTickets)

/** Exécute une action ; renvoie le résultat, ou null en cas d'échec (message affiché). */
async function agir<T = any>(fn: () => Promise<T>, ok: string, rechargerRef = false): Promise<T | null> {
  if (busy.value) return null
  busy.value = true
  try {
    const r = await fn()
    toast.ok(ok)
    await rechargerReferentiels()   // projets et membres : « tâches actives » doit toujours refléter l'état réel (fermeture, détachement…)
    await loadTickets()
    return r
  } catch (e: any) { toast.err(e.message); return null } finally { busy.value = false }
}

// ----- Statut, avancement, motifs, rattachement -----
async function changerStatut(e: Event) {
  const el = e.target as HTMLSelectElement, s = el.value
  if (!sel.value || !s || s === sel.value.statut) return
  if (s === 'en_attente') { categorie.value = ''; motif.value = ''; modal.value = 'attente'; return }
  if (!(await confirmer.ask({ title: 'Changer le statut ?', message: `Le ticket passera de « ${STATUT[sel.value.statut]} » à « ${STATUT[s]} ».`, confirmLabel: 'Changer le statut' }))) { el.value = sel.value.statut; return }
  const r = await agir(() => send('PUT', `/tickets/${sel.value.id}/statut`, { statut: s, auteur_id: auteur.value }), `Statut : ${STATUT[s]}`)
  if (!r && sel.value) el.value = sel.value.statut
}
function annulerAttente() { modal.value = ''; if (selStatut.value && sel.value) selStatut.value.value = sel.value.statut }
async function confirmerAttente() {
  if (!categorie.value) return toast.err("Choisissez un motif d'attente")
  if (categorie.value === 'autre' && !motif.value.trim()) return toast.err('Précisez le motif (texte libre)')
  modal.value = ''
  const r = await agir(() => send('PUT', `/tickets/${sel.value.id}/statut`,
    { statut: 'en_attente', auteur_id: auteur.value, categorie: categorie.value, motif: motif.value || null }), 'Ticket mis en attente (motif enregistré)')
  if (!r && selStatut.value && sel.value) selStatut.value.value = sel.value.statut
}
async function avancer(v: number) {
  if (!avancementModifiable.value || v === sel.value.avancement_declare) return
  if (!(await confirmer.ask({ title: 'Modifier l\'avancement ?', message: v === 100 ? 'À 100 %, le ticket garde son statut : sa clôture sera validée par le haut responsable.' : `L'avancement déclaré passera à ${v} %.`, confirmLabel: 'Confirmer' }))) return
  await agir(() => send('PUT', `/tickets/${sel.value.id}/avancement`, { avancement: v, auteur_id: auteur.value }),
    v === 100 ? 'Avancement à 100 % : le statut est conservé, la clôture attend la validation du haut responsable' : `Avancement déclaré : ${v} %`)
}
async function saisirRetard() {
  if (!(await confirmer.ask({ title: 'Enregistrer le motif de retard ?', confirmLabel: 'Enregistrer' }))) return
  const r = await agir(() => send('PUT', `/tickets/${sel.value.id}/motif-retard`, { motif: motifRetard.value, auteur_id: auteur.value }), 'Motif de retard enregistré')
  if (r) motifRetard.value = ''
}
/** Ferme la fenêtre du ticket (le tableau reste affiché derrière). */
function fermerDetail() { sel.value = null; hist.value = null; editing.value = false }

// ----- Création : projet, membre, ticket -----
function ouvrirTicket() {
  nouveau.value = { titre: '', description: '', projet_id: Number(projetId.value) || projets.value[0]?.id || '', echeance: '', membre_ids: [], depend_de_ids: [] }
  modal.value = 'ticket'
}
async function creerTicket() {
  const f = nouveau.value
  if (f.titre.trim().length < 2) return toast.err('Le titre est obligatoire')
  if (!f.projet_id) return toast.err('Choisissez un projet (ou créez-en un)')
  if (!f.echeance) return toast.err("L'échéance initiale est obligatoire")
  const r = await agir(() => send('POST', '/equipe/tickets', {
    titre: f.titre.trim(), description: f.description, projet_id: f.projet_id, echeance: f.echeance,
    membre_ids: f.membre_ids, depend_de_ids: f.depend_de_ids }), 'Ticket créé')
  if (r) { modal.value = ''; await choisir(r) }
}
async function creerProjet() {
  if (nvProjet.value.trim().length < 2) return toast.err('Nom de projet trop court')
  const cle = (x: string) => x.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/\s+/g, ' ').trim().toLowerCase()
  const deja = projets.value.find((p) => cle(p.nom) === cle(nvProjet.value))
  if (deja) return toast.err(`Un projet nommé « ${deja.nom} » existe déjà. Choisissez un autre nom de projet.`)
  const r = await agir(() => send('POST', '/equipe/projets', { nom: nvProjet.value.trim() }), 'Projet créé', true)
  if (r) { modal.value = ''; nvProjet.value = ''; projetId.value = r.id }
}
function ouvrirFormMembre(m?: any) {
  nvMembre.value = { id: m?.id ?? null, nom: m?.nom ?? '', profil: m?.profil ?? '', email: m?.email ?? '', fichier: null, apercu: null, photoActuelle: photoCrm(m?.photo) }
  modal.value = 'membre'
}
function choisirPhotoMembre(e: Event) {
  const input = e.target as HTMLInputElement, f = input.files?.[0]
  input.value = ''
  if (!f) return
  if (!/^image\//.test(f.type)) return toast.err('Choisissez une image (PNG, JPEG, WebP ou GIF).')
  if (f.size > 5 * 1024 * 1024) return toast.err('Image trop lourde (5 Mo maximum).')
  nvMembre.value.fichier = f
  nvMembre.value.apercu = URL.createObjectURL(f)
}
async function enregistrerMembre() {
  const m = nvMembre.value
  if (!m.nom.trim() || !m.profil.trim() || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(m.email)) return toast.err('Nom, profil et e-mail valide sont obligatoires')
  const corps = { nom: m.nom, profil: m.profil, email: m.email }
  if (m.id && !(await confirmer.ask({ title: 'Enregistrer les modifications ?', message: `Le membre « ${m.nom} » sera mis à jour dans toute l'application.`, confirmLabel: 'Enregistrer' }))) return
  const r = await agir(async () => {
    const saved = m.id ? await send('PUT', `/membres/${m.id}`, corps) : await send('POST', '/membres', corps)
    if (m.fichier) {
      const fd = new FormData(); fd.append('fichier', m.fichier)
      await crmApi(`/membres/${saved.id}/photo`, { method: 'POST', body: fd })
    }
    return saved
  }, m.id ? 'Membre modifié' : 'Membre créé', true)
  if (r) modal.value = 'membres'
}
async function retirerPhotoMembre() {
  const id = nvMembre.value.id
  if (!id) { nvMembre.value.fichier = null; nvMembre.value.apercu = null; return }
  if (!(await confirmer.ask({ title: 'Supprimer la photo ?', confirmLabel: 'Supprimer' }))) return
  const r = await agir(() => send('DELETE', `/membres/${id}/photo`), 'Photo supprimée', true)
  if (r) { nvMembre.value.photoActuelle = null; nvMembre.value.fichier = null; nvMembre.value.apercu = null }
}
function demanderSuppressionMembre(m: any) { membreASupprimer.value = m; modal.value = 'suppr_membre' }
async function supprimerMembre() {
  const m = membreASupprimer.value
  modal.value = 'membres'
  await agir(() => send('DELETE', `/membres/${m.id}`), `${m.nom} supprimé`, true)
}
/** Suppression d'un projet (avec tous ses tickets) : depuis la liste « Gérer les projets » ou depuis le filtre courant. */
const projetASupprimer = ref<any>(null)
function demanderSuppressionProjet(p: any) { projetASupprimer.value = p; modal.value = 'suppr_projet' }
async function supprimerProjet() {
  const p = projetASupprimer.value
  if (!p) return
  modal.value = ''
  const r = await agir(() => send('DELETE', `/projets/${p.id}`), `Projet « ${p.nom} » supprimé avec tous ses tickets`, true)
  projetASupprimer.value = null
  if (r) { if (projetId.value === p.id) projetId.value = ''; fermerDetail() }
  else if (modal.value === '') modal.value = 'projets'
}
const projetCourant = computed(() => projets.value.find((p) => p.id === projetId.value) ?? null)
const nbTicketsDe = (id: number) => tous.value.filter((t) => t.projet_id === id).length
const nbTicketsProjet = computed(() => (projetASupprimer.value ? nbTicketsDe(projetASupprimer.value.id) : 0))

// ----- Modification et suppression d'un ticket -----
async function supprimer() {
  const r = await agir(() => send('DELETE', `/tickets/${sel.value.id}`), `${tid(sel.value.id)} supprimé`)
  modal.value = ''
  if (r) fermerDetail()
}

const candidatsCreation = computed(() => tous.value.filter((t) => t.projet_id === nouveau.value.projet_id))
const bloque = computed(() => sel.value ? tous.value.filter((o) => o.depend_de_ids.includes(sel.value.id)) : [])
const bloqueTxt = computed(() => bloque.value.map((o) => tid(o.id)).join(', '))
const shown = computed(() => {
  const n = q.value.trim().toLowerCase()
  return n ? tickets.value.filter((t) => (tid(t.id) + ' ' + t.titre).toLowerCase().includes(n)) : tickets.value
})
// Le motif de retard n'a de sens que si l'échéance est réellement dépassée (jamais pour une échéance à venir)
const echeanceDepassee = computed(() => !!sel.value && (sel.value.est_en_retard || String(sel.value.echeance).slice(0, 10) < new Date().toLocaleDateString('sv-SE')))
const peutRetard = computed(() => sel.value && echeanceDepassee.value && ['ouvert', 'en_cours'].includes(sel.value.statut) && !sel.value.motif_retard_courant)
const timeline = computed(() => {
  if (!hist.value) return []
  const ev = [...hist.value.statuts.map((h: any) => ({ d: h.date, h })), ...hist.value.avancements.map((a: any) => ({ d: a.date, a }))]
  return ev.sort((x, y) => +new Date(y.d) - +new Date(x.d))
})
const ACTIONS = [
  { l: 'Membres', f: ouvrirMembres },
]
// Avancement : cliquable uniquement pour un ticket Ouvert ou En cours ; à 100 % le ticket se ferme automatiquement
const avancementModifiable = computed(() => !!sel.value && ['ouvert', 'en_cours'].includes(sel.value.statut))
const segAvancement = (v: number) => ['rounded-lg border px-2.5 py-1.5 text-xs font-medium tabular-nums transition disabled:cursor-not-allowed',
  sel.value?.avancement_declare === v ? 'border-brand-600 bg-brand-600 text-white' : 'border-slate-300 bg-white text-slate-600 enabled:hover:border-brand-300 enabled:hover:bg-brand-50 disabled:opacity-50']
</script>

<template>
  <div class="flex h-dvh flex-col overflow-hidden bg-surface">
    <header class="navbar-night flex shrink-0 flex-wrap items-center gap-3 px-4 py-3 text-white sm:px-8">
      <span class="relative grid size-9 place-items-center rounded-xl bg-white/15"><Icon name="list" :size="18" /></span>
      <div class="leading-tight"><p class="text-sm font-semibold">CRM Arato · espace équipe</p><p class="text-xs text-ciel">Simulateur pour tests et démonstration</p></div>
      <div class="relative ml-auto flex flex-wrap items-center gap-2">
        <button v-for="a in ACTIONS" :key="a.l" class="inline-flex items-center gap-1.5 rounded-xl bg-white/15 px-3 py-1.5 text-xs font-medium hover:bg-white/25" @click="a.f"><Icon name="users" :size="14" />{{ a.l }}</button>
        <RouterLink :to="auth.isAuthenticated ? '/' : '/login'" class="btn-sm inline-flex items-center gap-1.5 rounded-xl bg-white/15 px-3 py-1.5 text-xs font-medium hover:bg-white/25">
          <Icon name="sparkles" :size="14" /> Onglet « Agent IA »</RouterLink>
      </div>
    </header>

    <div class="scroller min-h-0 flex-1">
    <main class="mx-auto w-full max-w-[1680px] p-4 pb-16 sm:p-6 sm:pb-16 xl:px-10">
      <!-- Filtres -->
      <div class="mb-3 flex flex-wrap items-center gap-2">
        <select v-model="projetId" class="input w-auto!" aria-label="Projet"><option value="">Tous les projets</option><option v-for="p in projets" :key="p.id" :value="p.id">{{ p.nom }}</option></select>
        <select v-model="statutF" class="input w-auto!" aria-label="Statut"><option value="">Tous les statuts</option><option v-for="(l, k) in STATUT" :key="k" :value="k">{{ l }}</option></select>
        <div class="relative">
          <Icon name="search" :size="15" class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input v-model="q" type="search" class="input w-auto! min-w-[14rem] pl-9" placeholder="Rechercher…" aria-label="Rechercher un ticket" />
        </div>
        <button v-if="projetCourant" class="btn-danger btn-sm" @click="demanderSuppressionProjet(projetCourant)"><Icon name="trash" :size="13" />Supprimer ce projet</button>
        <button class="btn-secondary btn-sm" @click="modal = 'projets'"><Icon name="folder" :size="13" />Gérer les projets</button>
        <span class="ml-auto text-sm text-slate-500">{{ shown.length }} ticket{{ shown.length > 1 ? 's' : '' }}</span>
      </div>

      <!-- Tableau complet sur une seule page : un clic sur une ligne ouvre le ticket dans une fenêtre -->
      <div class="card overflow-x-auto">
        <table class="table-clean">
          <thead><tr><th>Ticket</th><th>Projet</th><th>Statut</th><th>Avancement</th><th>Échéance</th><th>Membres</th><th class="w-8" /></tr></thead>
          <tbody>
            <tr v-for="t in shown" :key="t.id" class="row-link" :class="sel?.id === t.id && 'bg-brand-50'" tabindex="0" role="button"
              :aria-label="`Ouvrir ${tid(t.id)}`" @click="choisir(t)" @keyup.enter="choisir(t)">
              <td><b class="text-brand-700">{{ tid(t.id) }}</b><p class="max-w-[22rem] truncate text-slate-700" :title="t.titre">{{ t.titre }}</p></td>
              <td class="text-slate-600">{{ nomProjet(t.projet_id) }}</td>
              <td><StatutBadge :statut="t.statut" /></td>
              <td><ProgressBar :value="t.avancement_declare" :tone="t.est_en_retard ? 'red' : t.statut === 'ferme' ? 'slate' : 'brand'" /></td>
              <td class="whitespace-nowrap text-slate-600">{{ fmtDate(t.echeance) }}<span v-if="t.est_en_retard" class="badge-red ml-1.5">retard</span></td>
              <td><div class="flex items-center gap-2"><span class="flex -space-x-2"><Avatar v-for="id in t.membre_ids.slice(0, 3)" :key="id" :nom="nomMembre(id)" :src="photoCrm(membres.find((m) => m.id === id)?.photo)" :size="24" ring /></span><span class="text-xs text-slate-500">{{ t.membre_ids.map(nomMembre).join(', ') || '—' }}</span></div></td>
              <td class="text-right text-slate-300"><Icon name="right" :size="16" /></td>
            </tr>
            <tr v-if="!shown.length"><td colspan="7" class="py-10 text-center text-sm text-slate-500">Aucun ticket ne correspond à ces filtres.</td></tr>
          </tbody>
        </table>
      </div>
    </main>
    </div>

    <!-- Fiche du ticket : visualisation et modification dans une fenêtre -->
    <Modal :open="!!sel" size="xl" @close="fermerDetail">
      <template #header>
        <template v-if="sel">
          <p class="flex items-center gap-2 text-xs font-semibold text-brand-700">{{ tid(sel.id) }}<StatutBadge :statut="sel.statut" /><span v-if="sel.est_en_retard" class="badge-red">retard</span></p>
          <h2 class="mt-1 text-lg font-semibold leading-snug text-slate-900">{{ sel.titre }}</h2>
          <p class="mt-0.5 text-sm text-slate-500">{{ nomProjet(sel.projet_id) }}</p>
        </template>
      </template>
      <template #actions>
        <template v-if="sel">
          <button class="btn-danger btn-sm" :disabled="busy" @click="modal = 'suppression'"><Icon name="trash" :size="13" />Supprimer</button>
        </template>
      </template>

      <template v-if="sel">
        <!-- Mode visualisation / actions -->
        <div class="grid gap-6 md:grid-cols-2">
          <div class="space-y-4">
            <p v-if="sel.description" class="whitespace-pre-wrap text-sm leading-relaxed text-slate-600">{{ sel.description }}</p>
            <p v-else class="text-sm text-slate-400">Aucune description.</p>
            <div v-if="sel.depend_de_ids.length || bloque.length" class="space-y-1 text-xs text-slate-600">
              <p v-if="sel.depend_de_ids.length">Dépend de : <b>{{ sel.depend_de_ids.map(tid).join(', ') }}</b></p>
              <p v-if="bloque.length">Bloque : <b>{{ bloqueTxt }}</b></p>
            </div>

            <p class="flex items-center gap-2 text-sm text-slate-600"><Icon name="calendar" :size="15" class="text-slate-400" />Échéance <b class="text-slate-900">{{ fmtDate(sel.echeance) }}</b><span v-if="sel.est_en_retard" class="badge-red">En retard</span></p>

            <div><p class="label">Membres rattachés</p>
              <div class="flex flex-wrap gap-1.5"><span v-for="id in sel.membre_ids" :key="id" class="inline-flex items-center gap-1.5 rounded-full border border-line bg-white px-2.5 py-1 text-xs font-medium text-slate-700"><Avatar :nom="nomMembre(id)" :src="photoCrm(membres.find((m) => m.id === id)?.photo)" :size="18" />{{ nomMembre(id) }}</span>
                <span v-if="!sel.membre_ids.length" class="text-xs text-slate-400">Aucun membre rattaché.</span></div></div>

            <div v-if="timeline.length"><p class="label">Historique</p>
              <ul class="max-h-52 space-y-1.5 overflow-y-auto text-xs text-slate-600">
                <li v-for="(e, i) in timeline" :key="i"><span class="text-slate-400">{{ fmtDateTime(e.d) }}</span> ·
                  <template v-if="e.a">avancement {{ e.a.ancienne }} % → {{ e.a.nouvelle }} %</template>
                  <template v-else-if="e.h.type_motif">motif de {{ e.h.type_motif }} : <b>{{ e.h.motif }}</b></template>
                  <template v-else>statut : {{ STATUT[e.h.statut] }}</template></li></ul></div>
          </div>

          <div class="space-y-4 md:border-l md:border-line md:pl-6">
            <div><label class="label" for="aut">Agir en tant que</label>
              <select id="aut" v-model="auteur" class="input"><option v-for="id in sel.membre_ids" :key="id" :value="id">{{ nomMembre(id) }}</option></select>
              <p v-if="!sel.membre_ids.length" class="mt-1 text-xs text-amber-700">Aucun membre n'est rattaché à ce ticket.</p></div>

            <fieldset :disabled="!auteur || busy" class="space-y-4">
              <div>
                <label class="label" for="st">Statut</label>
                <select id="st" ref="selStatut" class="input" :value="sel.statut" :disabled="sel.statut === 'ferme'" @change="changerStatut">
                  <option v-for="(l, k) in STATUT" v-show="k !== 'ferme' || sel.statut === 'ferme'" :key="k" :value="k" :disabled="k === 'ferme'">{{ l }}</option></select>
              </div>
              <div>
                <p class="label">Avancement déclaré</p>
                <div class="flex flex-wrap gap-1.5" role="group" aria-label="Avancement déclaré">
                  <button v-for="v in [0, 25, 50, 75, 100]" :key="v" type="button" :disabled="!avancementModifiable || busy" :class="segAvancement(v)"
                    :aria-pressed="sel.avancement_declare === v" @click="avancer(v)">{{ v }} %</button>
                </div>
                <p v-if="!avancementModifiable" class="mt-1.5 flex items-center gap-1.5 text-xs text-slate-500"><Icon name="lock" :size="12" />L'avancement ne se modifie que pour un ticket « Ouvert » ou « En cours ».</p>
                <p v-else class="mt-1.5 text-xs text-slate-500">L'avancement est indépendant du statut : même à 100 %, la clôture est validée par le haut responsable (espace « Agent IA »).</p>
              </div>
              <p v-if="sel.motif_attente_courant" class="rounded-lg bg-amber-50 p-2.5 text-xs text-amber-900"><Icon name="lock" :size="12" class="mr-1 inline" />Motif d'attente verrouillé : « {{ sel.motif_attente_courant }} »</p>
              <p v-if="sel.motif_retard_courant" class="rounded-lg bg-red-50 p-2.5 text-xs text-red-900"><Icon name="lock" :size="12" class="mr-1 inline" />Motif de retard verrouillé : « {{ sel.motif_retard_courant }} »</p>
              <div v-if="peutRetard"><label class="label" for="mr">Motif de retard (optionnel)</label>
                <div class="flex gap-2"><input id="mr" v-model="motifRetard" class="input" placeholder="Cause du retard" @keyup.enter="motifRetard.trim().length >= 3 && saisirRetard()" /><button class="btn-secondary shrink-0" :disabled="motifRetard.trim().length < 3" @click="saisirRetard">Enregistrer</button></div></div>
            </fieldset>
          </div>
        </div>
      </template>

      <template #footer>
        <button class="btn-secondary" @click="fermerDetail">Fermer</button>
      </template>
    </Modal>

    <!-- Motif d'attente -->
    <ConfirmModal :open="modal === 'attente'" title="Raison d'attente obligatoire" confirm-label="Mettre en attente" @confirm="confirmerAttente" @cancel="annulerAttente">
      <p class="mb-3">Sans motif, la transition vers « en attente » est impossible.</p>
      <label class="label" for="cat">Motif</label>
      <select id="cat" v-model="categorie" class="input"><option value="" disabled>Choisir…</option><option v-for="m in MOTIFS" :key="m" :value="m">{{ m }}</option></select>
      <label class="label mt-3" for="lib">Précision (texte libre{{ categorie === 'autre' ? ', obligatoire' : '' }})</label>
      <input id="lib" v-model="motif" class="input" />
    </ConfirmModal>

    <!-- Nouveau ticket -->
    <ConfirmModal :open="modal === 'ticket'" title="Nouveau ticket" confirm-label="Créer le ticket" @confirm="creerTicket" @cancel="modal = ''">
      <div class="space-y-3 text-left">
        <div><label class="label" for="nt">Titre</label><input id="nt" v-model="nouveau.titre" class="input" /></div>
        <div><label class="label" for="nds">Description</label><textarea id="nds" v-model="nouveau.description" rows="3" class="input" /></div>
        <div class="grid grid-cols-2 gap-3">
          <div><label class="label" for="np">Projet</label>
            <select id="np" v-model="nouveau.projet_id" class="input" @change="nouveau.depend_de_ids = []">
              <option value="" disabled>Choisir…</option><option v-for="p in projets" :key="p.id" :value="p.id">{{ p.nom }}</option></select></div>
          <div><label class="label" for="ne">Échéance initiale</label><input id="ne" v-model="nouveau.echeance" type="date" class="input" /></div>
        </div>
        <div><p class="label">Membres rattachés</p>
          <div class="flex flex-wrap gap-1.5"><button v-for="m in membres" :key="m.id" type="button" :class="chip(nouveau.membre_ids.includes(m.id))" @click="basculer(nouveau.membre_ids, m.id)">{{ m.nom }}</button></div></div>
        <div v-if="candidatsCreation.length"><p class="label">Dépend de</p>
          <div class="flex max-h-28 flex-wrap gap-1.5 overflow-y-auto"><button v-for="t in candidatsCreation" :key="t.id" type="button" :title="t.titre" :class="chip(nouveau.depend_de_ids.includes(t.id))" @click="basculer(nouveau.depend_de_ids, t.id)">{{ tid(t.id) }}</button></div></div>
      </div>
    </ConfirmModal>

    <!-- Nouveau projet -->
    <ConfirmModal :open="modal === 'projet'" title="Nouveau projet" confirm-label="Créer le projet" @confirm="creerProjet" @cancel="modal = ''">
      <label class="label" for="npj">Nom du projet</label>
      <input id="npj" v-model="nvProjet" class="input" @keyup.enter="creerProjet" />
    </ConfirmModal>

    <!-- Équipe : liste des membres, modification et suppression sécurisée -->
    <Modal :open="modal === 'membres'" size="lg" title="Membres de l'équipe" subtitle="Un membre rattaché à au moins une tâche active ne peut pas être supprimé." @close="modal = ''">
      <template #actions><button class="btn-primary btn-sm" @click="ouvrirFormMembre()"><Icon name="plus" :size="14" />Nouveau membre</button></template>
      <ul class="divide-y divide-line">
        <li v-for="m in membres" :key="m.id" class="flex flex-wrap items-center gap-3 py-3">
          <Avatar :nom="m.nom" :src="photoCrm(m.photo)" :size="44" />
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-semibold text-slate-900">{{ m.nom }}</p>
            <p class="truncate text-xs text-slate-500">{{ m.profil }} · {{ m.email }}</p>
          </div>
          <span v-if="m.taches_actives?.length" class="badge-amber" :title="m.taches_actives.map(tid).join(', ')">{{ m.taches_actives.length }} tâche{{ m.taches_actives.length > 1 ? 's' : '' }} active{{ m.taches_actives.length > 1 ? 's' : '' }}</span>
          <span v-else class="badge-slate">Aucune tâche active</span>
          <button class="btn-danger btn-sm" :disabled="busy || !!m.taches_actives?.length"
            :title="m.taches_actives?.length ? 'Suppression impossible : membre rattaché à une tâche active' : 'Supprimer ce membre'" @click="demanderSuppressionMembre(m)"><Icon name="trash" :size="13" />Supprimer</button>
        </li>
        <li v-if="!membres.length" class="py-8 text-center text-sm text-slate-500">Aucun membre.</li>
      </ul>
      <template #footer><button class="btn-secondary" @click="modal = ''">Fermer</button></template>
    </Modal>

    <!-- Nouveau membre / modification (avec photo de profil) -->
    <ConfirmModal :open="modal === 'membre'" :title="nvMembre.id ? 'Modifier le membre' : 'Nouveau membre'" :confirm-label="nvMembre.id ? 'Enregistrer' : 'Créer le membre'" :busy="busy" @confirm="enregistrerMembre" @cancel="modal = nvMembre.id || membres.length ? 'membres' : ''">
      <div class="space-y-3 text-left">
        <div class="flex items-center gap-4">
          <Avatar :nom="nvMembre.nom || 'Nouveau'" :src="nvMembre.apercu || nvMembre.photoActuelle" :size="64" />
          <div class="flex flex-wrap gap-2">
            <label class="btn-secondary btn-sm cursor-pointer"><Icon name="camera" :size="13" />{{ nvMembre.apercu || nvMembre.photoActuelle ? 'Changer la photo' : 'Ajouter une photo' }}
              <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" class="sr-only" @change="choisirPhotoMembre" /></label>
            <button v-if="nvMembre.apercu || nvMembre.photoActuelle" type="button" class="btn-ghost btn-sm" @click="retirerPhotoMembre"><Icon name="trash" :size="13" />Retirer</button>
          </div>
        </div>
        <div><label class="label" for="mn">Nom</label><input id="mn" v-model="nvMembre.nom" class="input" /></div>
        <div><label class="label" for="mp">Profil</label><input id="mp" v-model="nvMembre.profil" class="input" placeholder="Développeur, Designer…" /></div>
        <div><label class="label" for="me">E-mail</label><input id="me" v-model="nvMembre.email" type="email" class="input" /></div>
      </div>
    </ConfirmModal>

    <ConfirmModal :open="modal === 'suppr_membre'" title="Supprimer ce membre ?" confirm-label="Supprimer" @confirm="supprimerMembre" @cancel="modal = 'membres'">
      <p><b>{{ membreASupprimer?.nom }}</b> sera supprimé de l'équipe. Cette action est définitive.</p>
    </ConfirmModal>

    <!-- Gestion des projets : liste complète, suppression de n'importe quel projet -->
    <Modal :open="modal === 'projets'" title="Projets du CRM" @close="modal = ''">
      <p class="mb-3 text-sm text-slate-500">Supprimer un projet supprime aussi tous ses tickets, leurs historiques et leurs dépendances. L'agent IA met son suivi à jour tout seul.</p>
      <ul v-if="projets.length" class="max-h-[22rem] divide-y divide-line overflow-y-auto rounded-xl border border-line">
        <li v-for="p in projets" :key="p.id" class="flex items-center gap-3 px-4 py-3">
          <Icon name="folder" :size="16" class="shrink-0 text-slate-400" />
          <div class="min-w-0 flex-1"><p class="truncate text-sm font-medium text-slate-900">{{ p.nom }}</p>
            <p class="text-xs text-slate-500">{{ nbTicketsDe(p.id) }} ticket{{ nbTicketsDe(p.id) > 1 ? 's' : '' }}<template v-if="p.clos"> · clos</template></p></div>
          <button class="btn-danger btn-sm" :disabled="busy" :aria-label="`Supprimer le projet ${p.nom}`" @click="demanderSuppressionProjet(p)"><Icon name="trash" :size="13" />Supprimer</button>
        </li>
      </ul>
      <p v-else class="rounded-xl border border-line px-4 py-6 text-center text-sm text-slate-500">Aucun projet dans le CRM.</p>
    </Modal>

    <!-- Suppression d'un projet : en cascade sur tous ses tickets -->
    <ConfirmModal :open="modal === 'suppr_projet'" title="Supprimer ce projet ?" confirm-label="Supprimer le projet" @confirm="supprimerProjet" @cancel="modal = projets.length ? 'projets' : ''">
      <p>Le projet « <b>{{ projetASupprimer?.nom }}</b> » sera supprimé avec ses <b>{{ nbTicketsProjet }}</b> ticket(s), leurs historiques et leurs dépendances. Cette action est définitive.</p>
    </ConfirmModal>

    <!-- Suppression -->
    <ConfirmModal :open="modal === 'suppression'" title="Supprimer ce ticket ?" confirm-label="Supprimer" @confirm="supprimer" @cancel="modal = ''">
      <p>Le ticket <b>{{ sel && tid(sel.id) }}</b> et son historique seront définitivement supprimés.</p>
      <p v-if="bloque.length" class="mt-2 text-amber-700">Attention : {{ bloqueTxt }} en dépend{{ bloque.length > 1 ? 'ent' : '' }}, la suppression sera refusée.</p>
    </ConfirmModal>
  </div>
  <ToastHost />
</template>