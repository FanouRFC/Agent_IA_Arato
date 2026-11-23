<script setup lang="ts">
import { useAnalyseStore } from '@/stores/analyse'
import { useConfirmStore } from '@/stores/confirm'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { api, fmtDateTime, photoCrm, post, put } from '@/services/api'
import { useProjectStore } from '@/stores/project'
import { useToastStore } from '@/stores/toast'
import Avatar from '@/components/Avatar.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'
import EmptyState from '@/components/EmptyState.vue'
import Icon from '@/components/Icon.vue'
import PageHeader from '@/components/PageHeader.vue'
import { usePageBlanche } from '@/composables/usePageBlanche'

usePageBlanche()
const confirmer = useConfirmStore()
const toast = useToastStore()
const router = useRouter()
const project = useProjectStore()
const membres = ref<any[]>([]), cahiers = ref<any[]>([])
const nomAuto = ref(false), nom = ref(''), texte = ref(''), fichier = ref<File | null>(null), mode = ref<'fichier' | 'texte'>('fichier'), drag = ref(false)
const analyse = useAnalyseStore()
const busy = computed(() => analyse.busy)           // l'analyse continue même si l'on quitte la page
const cahier = ref<any>(null), validating = ref(false), confirm = ref(false), bilan = ref<any>(null), err = ref('')
const PRIORITES = [
  { v: 'haute', l: 'Haute', c: 'bg-red-500', t: 'text-red-700 bg-red-50' },
  { v: 'moyenne', l: 'Moyenne', c: 'bg-purple-500', t: 'text-purple-700 bg-purple-50' },
  { v: 'basse', l: 'Basse', c: 'bg-sky-400', t: 'text-sky-700 bg-sky-50' },
]
const prio = (v: string) => PRIORITES.find((p) => p.v === v) ?? PRIORITES[1]!
const open = ref<Set<number>>(new Set())
const affecter = ref<number | null>(null)
const fermerAffecter = () => { affecter.value = null }
onMounted(() => document.addEventListener('click', fermerAffecter))
onUnmounted(() => document.removeEventListener('click', fermerAffecter))

const step = computed(() => (bilan.value ? 3 : cahier.value ? 2 : 1))
const totalJours = computed(() => (cahier.value?.taches ?? []).reduce((s: number, t: any) => s + (t.duree_estimee || 0), 0))
const sansMembre = computed(() => (cahier.value?.taches ?? []).filter((t: any) => !(t.membre_ids ?? []).length))
const nbDeps = computed(() => (cahier.value?.taches ?? []).reduce((s: number, t: any) => s + (t.depend_de?.length || 0), 0))
const nbMembres = computed(() => new Set((cahier.value?.taches ?? []).flatMap((t: any) => t.membre_ids || [])).size)
/** Nom de projet unique : contrôle immédiat (liste des projets connus) puis contrôle du serveur (CRM compris, source de vérité). */
const cle = (x: string) => x.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/\s+/g, ' ').trim().toLowerCase()
const nomServeur = ref('')
const nomPris = computed(() => {
  const k = cle(nom.value)
  if (k.length < 2) return ''
  const local = project.projets.find((p) => cle(p.nom) === k)?.nom
  return local ? `Un projet nommé « ${local} » existe déjà. Choisissez un autre nom de projet.` : nomServeur.value
})
let minuterie: number | undefined
watch(nom, (v) => {
  nomServeur.value = ''
  clearTimeout(minuterie)
  if (cle(v).length < 2) return
  minuterie = window.setTimeout(async () => {
    try {
      const r = await api(`/projets/nom-disponible?nom=${encodeURIComponent(v)}`)
      if (v === nom.value) nomServeur.value = r.disponible ? '' : r.message
    } catch { /* le serveur refusera de toute façon un doublon à l'analyse */ }
  }, 300)
})
onUnmounted(() => clearTimeout(minuterie))
const canAnalyse = computed(() => nom.value.trim().length >= 2 && !nomPris.value && (mode.value === 'fichier' ? !!fichier.value : texte.value.trim().length >= 30))
const IDEES = ['lit le document en quelques secondes.', 'le découpe en tâches claires.', 'affecte les bonnes personnes.', 'calcule les échéances et les dépendances.', 'attend votre validation avant de créer quoi que ce soit.']
const ETAPES = [
  { i: 'upload', t: 'Vous déposez', d: 'PDF, Word ou simple texte collé.', puce: 'bg-[#F3F5F9] text-slate-600', bord: 'border-line', num: 'text-azur' },
  { i: 'sparkles', t: "L'agent propose", d: 'Tâches, durées, dépendances et membres.', puce: 'bg-[#F3F5F9] text-slate-600', bord: 'border-line', num: 'text-azur' },
  { i: 'check', t: 'Vous validez', d: 'Les tickets partent au CRM, les membres sont prévenus.', puce: 'bg-[#F3F5F9] text-slate-600', bord: 'border-line', num: 'text-azur' },
]
const idee = ref(0)
let rotation: number | undefined
onMounted(() => { rotation = window.setInterval(() => (idee.value = (idee.value + 1) % IDEES.length), 2600) })
onUnmounted(() => clearInterval(rotation))
const secondes = ref(0)
let chrono: number | undefined
const tic = () => { secondes.value = analyse.busy ? Math.floor((Date.now() - analyse.depart) / 1000) : 0 }
onMounted(() => { tic(); chrono = window.setInterval(tic, 1000) })
onUnmounted(() => clearInterval(chrono))

// Étapes affichées pendant l'analyse (la dernière reste active jusqu'à la réponse de l'agent)
const PHASES_BASE = ['Lecture du document', 'Décomposition en tâches', 'Affectation aux membres', 'Vérification de la cohérence']
const estScan = computed(() => /\.(png|jpe?g|webp|bmp|tiff?|gif|pdf)$/i.test(analyse.fichierNom || ''))
const PHASES = computed(() => estScan.value
  ? ['Reconnaissance du texte (OCR)', ...PHASES_BASE]
  : PHASES_BASE)
const phase = computed(() => Math.min(PHASES.value.length - 1, Math.floor(secondes.value / (estScan.value ? 15 : 7))))

async function init() {
  try {
    ;[membres.value, cahiers.value] = await Promise.all([api('/crm/membres'), api('/cahiers')])
  } catch (e: any) { err.value = e.message }
}
let syncMembres: number | undefined
onMounted(() => {
  init()
  // un membre ajouté ou modifié dans le CRM apparaît ici sans rechargement
  syncMembres = window.setInterval(async () => { if (document.hidden) return; try { membres.value = await api('/crm/membres') } catch { /* silencieux */ } }, 4000)
})
onUnmounted(() => window.clearInterval(syncMembres))

const EXT_OK = /\.(pdf|docx?|pptx?|xlsx?|odt|odp|ods|rtf|txt|md|csv|tsv|json|xml|log|html?|png|jpe?g|webp|bmp|tiff?|gif)$/i
const MAX_MO = 10

function pick(f?: File | null) {
  if (!f) return
  if (!EXT_OK.test(f.name)) { toast.err('Format non pris en charge.'); return }
  if (f.size > MAX_MO * 1024 * 1024) { toast.err(`Fichier trop volumineux (${MAX_MO} Mo max).`); return }
  fichier.value = f
  if (!nom.value || nomAuto.value) { nom.value = f.name.replace(/\.[^.]+$/, ''); nomAuto.value = true }
}

function retirerFichier() {
  fichier.value = null
  if (nomAuto.value) { nom.value = ''; nomAuto.value = false }
}
function onDrop(e: DragEvent) { drag.value = false; pick(e.dataTransfer?.files?.[0]) }

async function analyser() {
  err.value = ''
  const f = new FormData()
  f.append('nom_projet', nom.value.trim())
  if (mode.value === 'fichier' && fichier.value) f.append('fichier', fichier.value)
  else f.append('texte', texte.value)
  await analyse.lancer(f, nom.value.trim(), mode.value === 'fichier' ? (fichier.value?.name ?? '') : 'texte saisi')
}
/** Résultat de l'analyse (même si la page a été quittée puis rouverte) : brouillon à relire, ou erreur ; l'historique est rechargé. */
function adopter() {
  if (analyse.erreur) { err.value = analyse.erreur; analyse.effacerErreur() }
  const c = analyse.reprendre()
  if (c) { cahier.value = c; open.value = new Set([c.taches[0]?.id]) }
  init()
}
watch(() => analyse.busy, (b) => { if (!b) adopter() })
onMounted(() => { if (!analyse.busy) adopter() })

async function reprendre(id: number) {
  try { cahier.value = await api(`/cahiers/${id}`); bilan.value = null; open.value = new Set() } catch (e: any) { toast.err(e.message) }
}
const aSupprimer = ref<any>(null)
async function supprimerEntree() {
  const c = aSupprimer.value
  aSupprimer.value = null
  if (!c) return
  try { await api(`/cahiers/${c.id}`, { method: 'DELETE' }); toast.ok('Entrée supprimée de l\'historique.'); await init() } catch (e: any) { toast.err(e.message) }
}
async function abandonner() {
  if (!cahier.value) return
  if (!(await confirmer.ask({ title: 'Abandonner ce brouillon ?', message: 'Le cahier en cours et ses tâches seront supprimés.', confirmLabel: 'Abandonner' }))) return
  try { await api(`/cahiers/${cahier.value.id}`, { method: 'DELETE' }); cahier.value = null; await init(); toast.ok('Brouillon abandonné.') }
  catch (e: any) { toast.err(e.message) }
}

const save = (t: any) => put(`/taches/${t.id}`, {
  titre: t.titre, description: t.description, priorite: t.priorite, duree_estimee: Math.max(1, Number(t.duree_estimee) || 1),
  membre_ids: t.membre_ids, depend_de: t.depend_de, criteres_acceptation: (t.criteres_acceptation ?? []).filter((c: string) => c.trim().length >= 5),
}).catch((e: any) => toast.err(e.message))

async function remove(t: any) {
  if (!(await confirmer.ask({ title: 'Supprimer cette tâche ?', message: `« ${t.titre || 'Sans titre'} » sera retirée du cahier.`, confirmLabel: 'Supprimer' }))) return
  try {
    await api(`/taches/${t.id}`, { method: 'DELETE' })
    cahier.value.taches = cahier.value.taches.filter((x: any) => x.id !== t.id)
    for (const o of cahier.value.taches) o.depend_de = (o.depend_de || []).filter((d: number) => d !== t.ordre)
  } catch (e: any) { toast.err(e.message) }
}
async function ajouter() {
  try {
    const t = await post(`/cahiers/${cahier.value.id}/taches`, { titre: 'Nouvelle tâche', duree_estimee: 1 })
    cahier.value.taches.push(t); open.value.add(t.id)
  } catch (e: any) { toast.err(e.message) }
}
/** Validation : les tickets partent au CRM, puis un écran de transition confirme l'envoi (aucune redirection automatique). */
async function valider() {
  validating.value = true
  try {
    bilan.value = await post(`/cahiers/${cahier.value.id}/valider`)
    confirm.value = false
    await project.load()
    if (bilan.value.projet_id) project.recentId = bilan.value.projet_id    // mis en avant sur la page de choix du projet (jamais ouvert d'office)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  } catch (e: any) { toast.err(e.message); confirm.value = false }
  validating.value = false
}
function nouveau() { cahier.value = null; bilan.value = null; nom.value = ''; nomAuto.value = false; texte.value = ''; fichier.value = null; init() }

const ajouterCritere = (t: any) => { (t.criteres_acceptation ??= []).push('') }
const retirerCritere = (t: any, i: number) => { t.criteres_acceptation.splice(i, 1); save(t) }
const toggle = (id: number) => { const n = new Set(open.value); n.has(id) ? n.delete(id) : n.add(id); open.value = n }
const titreDe = (ordre: number) => cahier.value?.taches.find((t: any) => t.ordre === ordre)?.titre ?? `Tâche ${ordre}`
const membresDe = (t: any) => membres.value.filter((m) => (t.membre_ids || []).includes(m.id))
function toggleMembre(t: any, id: number) {
  const s = new Set<number>(t.membre_ids || []); s.has(id) ? s.delete(id) : s.add(id)
  t.membre_ids = [...s]; save(t)
}
function toggleDep(t: any, ordre: number) {
  const s = new Set<number>(t.depend_de || []); s.has(ordre) ? s.delete(ordre) : s.add(ordre)
  t.depend_de = [...s]; save(t)
}
const STATUT_CAHIER: Record<string, { l: string; c: string }> = {
  brouillon: { l: 'Brouillon', c: 'badge-amber' }, valide: { l: 'Validé', c: 'badge-green' }, partiel: { l: 'Partiel', c: 'badge-red' },
}
const STEPS = ['Déposer', 'Relire', 'Valider']
const confiance = (c: number) => (c >= 0.7 ? 'bg-sky-400' : c >= 0.4 ? 'bg-purple-500' : 'bg-red-500')
</script>

<template>
  <PageHeader title="Cahier des charges" subtitle="L'IA propose, vous validez : aucun ticket n'est créé avant votre validation.">
    <RouterLink v-if="!bilan" to="/projets" class="btn-secondary">Passer au suivi d'un projet <Icon name="right" :size="15" /></RouterLink>
  </PageHeader>

  <!-- Étapes : la ligne se remplit à mesure que l'on avance -->
  <ol class="mb-8 flex items-center" aria-label="Étapes">
    <template v-for="(s, i) in STEPS" :key="s">
      <li class="flex items-center gap-2.5" :aria-current="step === i + 1 ? 'step' : undefined">
        <span class="grid size-8 place-items-center rounded-full text-xs font-semibold transition-all duration-500"
          :class="step > i + 1 ? 'bg-gradient-to-br from-azur to-primary text-white' : step === i + 1 ? 'bg-gradient-to-br from-primary to-violet-arato text-white shadow-[0_0_0_5px_rgb(29_78_133/0.15)]' : 'bg-slate-200 text-slate-500'">
          <Icon v-if="step > i + 1" name="check" :size="14" /><template v-else>{{ i + 1 }}</template></span>
        <span class="text-sm" :class="step === i + 1 ? 'font-semibold text-slate-900' : 'text-slate-500'">{{ s }}</span>
      </li>
      <li v-if="i < STEPS.length - 1" class="mx-3 h-0.5 w-10 overflow-hidden rounded-full bg-slate-200 sm:w-20" aria-hidden="true">
        <span class="block h-full rounded-full bg-gradient-to-r from-primary to-violet-arato transition-all duration-700" :style="{ width: step > i + 1 ? '100%' : '0%' }" />
      </li>
    </template>
  </ol>

  <p v-if="err" class="mb-4 flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert"><Icon name="alert" :size="16" class="mt-0.5" />{{ err }}</p>

  <!-- Écran de transition après la validation -->
  <section v-if="bilan" class="card rise relative overflow-hidden px-6 py-14 text-center sm:py-16">
    <div class="pointer-events-none absolute left-1/2 top-0 size-80 -translate-x-1/2 -translate-y-1/2 rounded-full bg-gradient-to-br from-azur/30 to-violet-arato/25 blur-3xl" aria-hidden="true" />
    <div class="relative">
      <span class="pop mx-auto grid size-20 place-items-center rounded-full text-white shadow-lg"
        :class="bilan.erreurs.length ? 'bg-gradient-to-br from-purple-500 to-red-500' : 'bg-gradient-to-br from-azur via-primary to-violet-arato'">
        <svg v-if="!bilan.erreurs.length" viewBox="0 0 24 24" width="38" height="38" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M5 12.5l4.5 4.5L19 7.5" stroke-dasharray="26" stroke-dashoffset="26" style="animation: draw .6s .35s ease-out forwards" /></svg>
        <Icon v-else name="alert" :size="34" />
      </span>
      <h2 class="display mt-6 text-3xl text-slate-900">{{ bilan.erreurs.length ? 'Envoi partiel au CRM' : 'Les tickets ont bien été envoyés au CRM' }}</h2>
      <p class="mx-auto mt-3 max-w-lg text-sm leading-relaxed text-slate-600">
        Projet « <b class="text-slate-900">{{ bilan.projet }}</b> » créé · {{ bilan.tickets_crees }} ticket(s) envoyé(s).
      </p>
      <!-- Bilan des e-mails : toujours dit clairement, qu'ils soient partis, bloqués ou impossibles -->
      <ul class="mx-auto mt-5 max-w-lg space-y-2 text-left text-sm">
        <li v-if="bilan.mails_envoyes && bilan.envoi_reel" class="flex items-start gap-2.5 rounded-xl border border-line bg-white p-3"><Icon name="check" :size="16" class="mt-0.5 shrink-0 text-slate-900" />
          <span><b class="text-slate-900">{{ bilan.mails_envoyes }} e-mail(s) d'affectation envoyé(s)</b> à {{ bilan.destinataires.join(', ') }}.</span></li>
        <li v-else-if="bilan.mails_envoyes" class="flex items-start gap-2.5 rounded-xl border border-line bg-white p-3"><Icon name="alert" :size="16" class="mt-0.5 shrink-0 text-azur" />
          <span><b class="text-slate-900">{{ bilan.mails_envoyes }} e-mail(s) remis au serveur de test local.</b> Une copie de chaque message est conservée dans le dossier « data/outbox » du serveur ; aucune vraie boîte de réception ne les reçoit tant qu'un compte d'envoi réel n'est pas renseigné côté serveur.</span></li>
        <li v-if="bilan.mails_en_echec" class="flex items-start gap-2.5 rounded-xl border border-line bg-white p-3"><Icon name="alert" :size="16" class="mt-0.5 shrink-0 text-azur" />
          <span><b class="text-slate-900">{{ bilan.mails_en_echec }} e-mail(s) non envoyé(s).</b> Les tickets sont bien créés. <span v-if="bilan.mails_causes?.length" class="text-slate-500">Cause : {{ bilan.mails_causes.join(' · ') }}</span></span></li>
        <li v-if="bilan.taches_sans_membre" class="flex items-start gap-2.5 rounded-xl border border-line bg-white p-3"><Icon name="users" :size="16" class="mt-0.5 shrink-0 text-azur" />
          <span><b class="text-slate-900">{{ bilan.taches_sans_membre }} tâche(s) sans membre affecté</b> : personne n'est prévenu pour celles-ci. Affectez un ou plusieurs membres avant de valider.</span></li>
      </ul>
      <div v-if="bilan.erreurs.length" class="mx-auto mt-5 max-w-lg rounded-xl border border-red-200 bg-red-50 p-4 text-left text-sm text-red-800">
        <p class="font-medium">{{ bilan.erreurs.length }} ticket(s) n'ont pas pu être transmis au CRM :</p>
        <ul class="mt-1.5 list-disc space-y-0.5 pl-5"><li v-for="e in bilan.erreurs" :key="e">{{ e }}</li></ul>
        <p class="mt-2 text-xs text-red-700">Le cahier reste en statut « partiel » : validez-le de nouveau pour réessayer uniquement ces tickets.</p></div>
      <div class="mt-8 flex flex-wrap justify-center gap-3">
        <RouterLink to="/projets" class="btn-primary px-5 py-2.5 text-[15px]">Choisir un projet à suivre <Icon name="right" :size="16" /></RouterLink>
        <button class="btn-secondary px-5 py-2.5 text-[15px]" @click="nouveau">Déposer un autre cahier</button>
      </div>
    </div>
  </section>

  <!-- Étape 1 : dépôt -->
  <template v-else-if="!cahier">
    <section class="card rise relative overflow-hidden">
      <!-- Analyse en cours : étapes animées -->
      <div v-if="busy" class="relative px-6 py-12 text-center sm:px-10" role="status" aria-live="polite">
        <span class="relative mx-auto grid size-16 place-items-center rounded-2xl bg-gradient-to-br from-azur via-primary to-violet-arato text-white shadow-lg aura"><Icon name="sparkles" :size="28" class="floaty" /></span>
        <h2 class="display mt-5 text-2xl text-slate-900">L'agent analyse votre document</h2>
        <p class="muted mt-1">Avec un modèle en ligne, comptez une à deux minutes. <span class="tabular-nums">{{ secondes }} s</span></p>
        <ol class="mx-auto mt-7 max-w-sm space-y-3 text-left">
          <li v-for="(p, i) in PHASES" :key="p" class="flex items-center gap-3 text-sm transition-opacity duration-500" :class="i > phase ? 'opacity-40' : ''">
            <span class="grid size-6 shrink-0 place-items-center rounded-full text-white transition-colors duration-500"
              :class="i < phase ? 'bg-sky-400' : i === phase ? 'bg-brand-600' : 'bg-slate-300'">
              <Icon v-if="i < phase" name="check" :size="13" /><Icon v-else-if="i === phase" name="refresh" :size="13" class="animate-spin" /></span>
            <span :class="i === phase ? 'font-semibold text-slate-900' : 'text-slate-600'">{{ p }}<span v-if="i === phase">…</span></span>
          </li>
        </ol>
        <div class="mx-auto mt-7 h-1.5 max-w-sm overflow-hidden rounded-full bg-slate-100"><div class="shimmer h-full w-full bg-brand-300/60" /></div>
      </div>

      <div v-else class="theme-clair relative grid gap-8 bg-white p-6 sm:p-10 lg:grid-cols-[1fr_1.1fr] lg:items-center">
        <!-- Grand message d'accueil, qui change tout seul pour montrer ce que fera l'agent -->
        <div class="relative">
          <p class="inline-flex items-center gap-2 rounded-full border border-line bg-white px-3 py-1 text-xs font-semibold uppercase tracking-[.14em] text-slate-500"><span class="size-1.5 rounded-full bg-azur" />Étape 1 · Dépôt</p>
          <h2 class="display mt-5 text-[2.4rem] leading-[1.08] text-slate-900 sm:text-5xl">Déposez votre <span class="bg-[linear-gradient(transparent_66%,#DEEFEE_66%)]">cahier des charges</span>.</h2>
          <p class="mt-4 min-h-[3.4rem] text-xl text-slate-600" aria-live="polite">
            <Transition name="fade" mode="out-in"><span :key="idee" class="inline-block"><b class="font-semibold text-azur">L'agent</b> {{ IDEES[idee] }}</span></Transition></p>
          <ol class="mt-8 grid max-w-md gap-3">
            <li v-for="(e, k) in ETAPES" :key="e.t" class="group flex items-center gap-3 rounded-2xl border bg-white/90 px-4 py-3 shadow-sm backdrop-blur transition hover:-translate-y-0.5 hover:shadow-card" :class="e.bord">
              <span class="grid size-10 shrink-0 place-items-center rounded-xl transition group-hover:scale-105" :class="e.puce"><Icon :name="e.i" :size="18" /></span>
              <span class="text-sm"><b class="text-slate-900"><span class="mr-1 tabular-nums" :class="e.num">0{{ k + 1 }}</span>{{ e.t }}</b><span class="block text-slate-500">{{ e.d }}</span></span></li>
          </ol>
        </div>

        <!-- Zone de dépôt : carte structurée en deux blocs numérotés -->
        <div class="relative overflow-hidden rounded-3xl border border-line bg-white shadow-card">
          <div class="h-1 bg-azur" />
          <div class="p-5 sm:p-6">
            <p class="flex items-center gap-2 text-sm font-semibold text-slate-900"><span class="grid size-6 place-items-center rounded-full bg-azur text-xs text-white">1</span>Votre document</p>
            <div class="mt-3 inline-flex rounded-xl bg-[#F2F4F8] p-1 text-sm" role="tablist">
              <button v-for="m in (['fichier', 'texte'] as const)" :key="m" role="tab" :aria-selected="mode === m" class="rounded-lg px-3.5 py-1.5 font-medium transition"
                :class="mode === m ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-900'" @click="mode = m">{{ m === 'fichier' ? 'Importer un fichier' : 'Coller le texte' }}</button>
            </div>

            <label v-if="mode === 'fichier'" class="depot depot-couleur mt-3" :class="[drag && 'depot-actif', fichier && 'depot-pret']"
              @dragover.prevent="drag = true" @dragleave="drag = false" @drop.prevent="onDrop">
              <span class="depot-icone"><Icon :name="fichier ? 'file' : 'upload'" :size="30" /></span>
              <template v-if="!fichier">
                <span class="mt-4 text-lg font-semibold text-slate-900">{{ drag ? 'Relâchez pour déposer' : 'Glissez votre document ici' }}</span>
                <span class="mt-1 text-sm text-slate-500">ou <span class="font-medium text-azur underline decoration-2 underline-offset-4">parcourez vos fichiers</span></span>
              </template>
              <template v-else>
                <span class="mt-4 text-lg font-semibold text-slate-900">{{ fichier.name }}</span>
                <span class="mt-1 text-sm text-slate-500">{{ Math.round(fichier.size / 1024) }} Ko · prêt à être analysé</span>
                <button type="button" class="mt-3 text-xs font-medium text-slate-500 underline underline-offset-4 hover:text-slate-900" @click.prevent="retirerFichier">Choisir un autre fichier</button>
              </template>
              <span class="mt-5 flex gap-1.5 text-[11px] font-semibold uppercase tracking-wider"><span v-for="(f, k) in ['PDF','Word', 'Excel', 'PPT','Image','…']" :key="f" class="rounded-md px-2 py-0.5" :class="'bg-[#F3F5F9] text-slate-500'">{{ f }}</span><span class="px-1 py-0.5 normal-case tracking-normal text-slate-400">10 Mo max</span></span>
              <input type="file" accept=".pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.odt,.odp,.ods,.rtf,.txt,.md,.csv,.tsv,.json,.xml,.log,.html,.htm,image/*" class="sr-only" @change="(e: Event) => { const el = e.target as HTMLInputElement; pick(el.files?.[0]); el.value = '' }" />
            </label>
            <textarea v-else v-model="texte" rows="9" class="input mt-3 rounded-2xl" placeholder="Collez ici le contenu du cahier des charges…" aria-label="Texte du cahier des charges" />

            <p class="mt-6 flex items-center gap-2 text-sm font-semibold text-slate-900"><span class="grid size-6 place-items-center rounded-full bg-azur text-xs text-white">2</span>Nom du projet</p>
            <div class="mt-3"><label class="sr-only" for="np">Nom du projet</label>
              <input id="np" v-model="nom" class="input" :class="nomPris && 'border-red-400!'" placeholder="Ex. Portail client v2"
                :aria-invalid="!!nomPris" aria-describedby="np-err" />
              <p v-if="nomPris" id="np-err" class="mt-1.5 flex items-center gap-1.5 text-sm text-red-700" role="alert"><Icon name="alert" :size="14" />{{ nomPris }}</p></div>
            <button class="btn-primary mt-5 w-full justify-center py-3 text-[15px]" :disabled="!canAnalyse" @click="analyser"><Icon name="sparkles" :size="16" /> Lancer l'analyse par l'agent</button>
            <p class="mt-2 flex items-center justify-center gap-1.5 text-center text-xs text-slate-500"><Icon name="check" :size="12" />Rien n'est créé avant votre validation.</p>
          </div>
        </div>
      </div>
    </section>

    <section class="mt-8">
      <h2 class="card-title">Historique</h2>
      <div class="card mt-3 overflow-x-auto">
        <table v-if="cahiers.length || busy" class="table-clean">
          <thead><tr><th>Projet</th><th>Fichier</th><th>Déposé le</th><th>Tâches</th><th>Statut</th><th /></tr></thead>
          <tbody><tr v-if="busy" class="bg-amber-50/50" aria-live="polite">
            <td class="font-medium text-slate-900">{{ analyse.nom }}</td><td class="text-slate-600">{{ analyse.fichierNom }}</td>
            <td class="text-slate-600">{{ fmtDateTime(new Date(analyse.depart).toISOString()) }}</td><td class="tabular-nums">…</td>
            <td><span class="badge-amber">Analyse en cours · {{ secondes }} s</span></td><td />
          </tr>
          <tr v-for="c in cahiers" :key="c.id">
            <td class="font-medium text-slate-900">{{ c.nom_projet }}</td><td class="text-slate-600">{{ c.nom_fichier }}</td>
            <td class="text-slate-600">{{ fmtDateTime(c.date_depot) }}</td><td class="tabular-nums">{{ c.nb_taches }}</td>
            <td><span :class="STATUT_CAHIER[c.statut]?.c ?? 'badge-slate'">{{ STATUT_CAHIER[c.statut]?.l ?? c.statut }}</span></td>
            <td class="text-right whitespace-nowrap"><button v-if="c.statut !== 'valide'" class="btn-secondary btn-sm mr-2" @click="reprendre(c.id)">Reprendre</button>
              <button class="btn-danger btn-sm" :aria-label="`Supprimer l'entrée ${c.nom_projet}`" @click="aSupprimer = c"><Icon name="trash" :size="13" /> Supprimer</button></td>
          </tr></tbody>
        </table>
        <EmptyState v-else icon="file" title="Aucun cahier déposé" text="Les cahiers que vous déposez apparaissent ici, avec leur statut." />
      </div>
    </section>

    <ConfirmModal :open="!!aSupprimer" title="Supprimer cette entrée ?" confirm-label="Supprimer" @confirm="supprimerEntree" @cancel="aSupprimer = null">
      <p>L'entrée « <b>{{ aSupprimer?.nom_projet }}</b> » sera retirée de l'historique des cahiers des charges.</p>
      <p class="mt-2 text-slate-500">Le projet et les tickets déjà créés dans le CRM ne sont pas supprimés.</p>
    </ConfirmModal>
  </template>

  <!-- Étape 2 : relecture -->
  <template v-else>
    <div class="mb-5 flex flex-wrap items-center gap-3">
      <h2 class="display text-xl text-slate-900">{{ cahier.nom_projet }}</h2>
      <button class="btn-ghost btn-sm ml-auto" @click="cahier = null; init()"><Icon name="left" :size="14" /> Retour</button>
    </div>

    <!-- Synthèse de la proposition (quatre repères de même hauteur) -->
    <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <div v-for="(k, i) in [
        { v: cahier.taches.length, l: 'tâches proposées', i: 'list' },
        { v: totalJours, l: 'jours cumulés', i: 'calendar' },
        { v: nbMembres, l: 'membres mobilisés', i: 'users' },
        { v: nbDeps, l: 'dépendances', i: 'link' },
      ]" :key="k.l" class="card rise flex items-center gap-3 px-4 py-3.5" :style="{ animationDelay: Number(i) * 70 + 'ms' }">
        <span class="grid size-10 shrink-0 place-items-center rounded-xl bg-brand-100 text-brand-700"><Icon :name="k.i" :size="18" /></span>
        <div class="leading-tight"><p class="display text-2xl tabular-nums text-slate-900">{{ k.v }}</p><p class="text-xs text-slate-500">{{ k.l }}</p></div>
      </div>
    </div>

    <div v-if="cahier.ambiguites.length" class="mt-4 rounded-2xl border border-purple-200 bg-purple-50 p-4">
      <h3 class="flex items-center gap-2 text-sm font-semibold text-purple-900"><Icon name="alert" :size="16" /> Ambiguïtés et informations manquantes</h3>
      <ul class="mt-2 list-disc space-y-1 pl-5 text-sm text-purple-900"><li v-for="a in cahier.ambiguites" :key="a">{{ a }}</li></ul>
    </div>

    <p v-if="sansMembre.length" class="mt-5 flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert"><Icon name="alert" :size="16" class="mt-0.5 shrink-0" />
      <span><b>{{ sansMembre.length }} tâche{{ sansMembre.length > 1 ? 's' : '' }} sans membre affecté</b> : {{ sansMembre.map((t: any) => t.titre).join(', ') }}. Aucun ticket n'est envoyé tant que chaque tâche n'a pas au moins un membre : utilisez le bouton « Affecter ».</span></p>
    <p class="mb-4 mt-5 text-sm text-slate-600">Les membres sont affectés automatiquement selon leur profil et leur charge actuelle. Corrigez ce qui ne convient pas, puis validez.</p>

    <!-- Tâches en fil conducteur : une ligne verticale relie les étapes -->
    <ol class="relative space-y-3">
      <span v-if="cahier.taches.length > 1" class="absolute bottom-6 left-[1.1rem] top-6 w-px bg-gradient-to-b from-brand-300 via-purple-300 to-sky-300" aria-hidden="true" />
      <li v-for="(t, i) in cahier.taches" :key="t.id" class="rise relative flex gap-3" :class="affecter === t.id && 'z-40'" :style="{ animationDelay: Math.min(Number(i), 10) * 60 + 'ms' }">
        <span class="relative z-10 mt-3 grid size-9 shrink-0 place-items-center rounded-full border-2 border-white text-xs font-semibold text-white shadow" :class="prio(t.priorite).c">{{ Number(i) + 1 }}</span>
        <div class="card min-w-0 flex-1 transition hover:shadow-pop" :class="open.has(t.id) && 'ring-2 ring-brand-500/20'">
          <div class="flex flex-wrap items-center gap-3 px-4 py-3">
            <button class="grid size-7 place-items-center rounded-lg text-slate-400 transition hover:bg-brand-50 hover:text-brand-700" :aria-expanded="open.has(t.id)" aria-label="Déplier" @click="toggle(t.id)">
              <Icon name="down" :size="16" class="transition-transform duration-300" :class="open.has(t.id) ? '' : '-rotate-90'" /></button>
            <input v-model="t.titre" class="input min-w-48 flex-1 border-transparent! bg-transparent! font-medium shadow-none! hover:border-slate-300!" aria-label="Titre de la tâche" @change="save(t)" />
            <select v-model="t.priorite" class="input w-auto! py-1.5" :class="prio(t.priorite).t" aria-label="Priorité" @change="save(t)"><option v-for="p in PRIORITES" :key="p.v" :value="p.v">{{ p.l }}</option></select>
            <!-- Affectation : un ou plusieurs membres, directement depuis la ligne -->
            <div class="relative" @click.stop>
              <button type="button" class="inline-flex items-center gap-2 rounded-xl border bg-white px-2.5 py-1.5 text-sm transition hover:border-slate-400"
                :class="affecter === t.id ? 'border-slate-900' : (membresDe(t).length ? 'border-line' : 'border-azur text-azur')" :aria-expanded="affecter === t.id" @click="affecter = affecter === t.id ? null : t.id">
                <span v-if="membresDe(t).length" class="flex -space-x-2"><Avatar v-for="m in membresDe(t).slice(0, 3)" :key="m.id" :nom="m.nom" :src="photoCrm(m.photo)" :size="22" ring /></span>
                <Icon v-else name="users" :size="15" />
                <span class="font-medium" :class="membresDe(t).length > 0 && 'text-slate-700'">{{ membresDe(t).length ? (membresDe(t).length === 1 ? membresDe(t)[0].nom : membresDe(t).length + ' membres') : 'Affecter' }}</span>
                <Icon name="down" :size="13" class="text-slate-400" /></button>
              <div v-if="affecter === t.id" class="absolute right-0 z-30 mt-2 w-72 rounded-2xl border border-line bg-white p-2 shadow-pop">
                <p class="px-2 pb-1.5 pt-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">Cochez un ou plusieurs membres</p>
                <ul class="max-h-64 overflow-y-auto">
                  <li v-for="m in membres" :key="m.id"><label class="flex cursor-pointer items-center gap-2.5 rounded-xl px-2 py-1.5 transition hover:bg-slate-50">
                    <input type="checkbox" class="accent-slate-900" :checked="(t.membre_ids || []).includes(m.id)" @change="toggleMembre(t, m.id)" />
                    <Avatar :nom="m.nom" :src="photoCrm(m.photo)" :size="26" />
                    <span class="min-w-0 flex-1 leading-tight"><span class="block truncate text-sm font-medium text-slate-900">{{ m.nom }}</span><span class="block truncate text-xs text-slate-500">{{ m.profil }}</span></span></label></li>
                </ul>
                <p class="mt-1 border-t border-line px-2 pt-2 text-xs text-slate-500">Chaque membre coché reçoit un e-mail à la validation.</p>
              </div>
            </div>
            <label class="flex items-center gap-1.5 text-sm text-slate-600">
              <input v-model.number="t.duree_estimee" type="number" min="1" class="input w-16! py-1.5 text-center" aria-label="Durée en jours" @change="save(t)" /> j</label>
            <button class="btn-ghost btn-sm text-red-600" aria-label="Supprimer la tâche" @click="remove(t)"><Icon name="trash" :size="15" /></button>
          </div>
          <div v-if="t.depend_de?.length && !open.has(t.id)" class="flex flex-wrap items-center gap-1.5 rounded-b-2xl border-t border-line/70 bg-slate-50/60 px-4 py-1.5 text-xs text-slate-500">
            <Icon name="link" :size="12" /> Dépend de <span v-for="d in t.depend_de" :key="d" class="badge-slate max-w-48 truncate">{{ titreDe(d) }}</span></div>
          <Transition name="fade">
            <div v-show="open.has(t.id)" class="space-y-4 border-t border-line px-4 py-4">
              <div><label class="label">Description</label><textarea v-model="t.description" rows="3" class="input" @change="save(t)" /></div>
              <div>
                <p class="label">Critères d'acceptation <span class="font-normal text-slate-400">(générés à partir du document, modifiables)</span></p>
                <ul v-if="(t.criteres_acceptation || []).length" class="space-y-1.5">
                  <li v-for="(_c, i) in (t.criteres_acceptation as string[])" :key="i" class="flex items-center gap-2">
                    <span class="grid size-6 shrink-0 place-items-center rounded-full bg-slate-100 text-xs font-semibold text-slate-600">{{ Number(i) + 1 }}</span>
                    <input v-model="t.criteres_acceptation[i]" class="input flex-1" maxlength="400" :aria-label="'Critère ' + (Number(i) + 1)" @change="save(t)" />
                    <button class="btn-ghost btn-sm text-red-600" type="button" aria-label="Retirer le critère" @click="retirerCritere(t, Number(i))"><Icon name="trash" :size="14" /></button></li>
                </ul>
                <p v-else class="text-xs text-slate-500">Cette tâche n'a plus de critère : des critères par défaut, tirés de son énoncé, seront ajoutés à la validation.</p>
                <button class="btn-secondary btn-sm mt-2" type="button" :disabled="(t.criteres_acceptation || []).length >= 12" @click="ajouterCritere(t)">Ajouter un critère</button>
              </div>
              <div class="grid gap-4 md:grid-cols-2">
                <div>
                  <p class="label">Affectation <span class="font-normal text-slate-400">(proposée par l'IA, cliquez pour modifier)</span></p>
                  <p v-if="t.profil_recommande" class="mb-2 text-xs text-slate-500">Profil recommandé : {{ t.profil_recommande }}</p>
                  <div class="flex flex-wrap gap-1.5">
                    <button v-for="m in membres" :key="m.id" type="button" :title="m.profil"
                      class="chip" :class="(t.membre_ids || []).includes(m.id) ? 'chip-on' : 'chip-off'"
                      @click="toggleMembre(t, m.id)"><Avatar :nom="m.nom" :src="photoCrm(m.photo)" :size="18" />{{ m.nom }}</button>
                  </div>
                </div>
                <div><p class="label">Dépend de</p>
                  <div class="mb-2 flex flex-wrap gap-1.5"><span v-for="d in t.depend_de" :key="d" class="badge-slate max-w-full truncate">{{ titreDe(d) }}</span>
                    <span v-if="!t.depend_de.length" class="text-xs text-slate-400">Aucune dépendance</span></div>
                  <details v-if="cahier.taches.length > 1" class="rounded-xl border border-slate-300 bg-white"><summary class="cursor-pointer px-3 py-1.5 text-sm text-slate-600">Modifier les dépendances</summary>
                    <div class="max-h-44 space-y-0.5 overflow-y-auto border-t border-line p-2">
                      <label v-for="o in cahier.taches.filter((x: any) => x.id !== t.id)" :key="o.id" class="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1 text-sm hover:bg-brand-50">
                        <input type="checkbox" class="accent-brand-600" :checked="(t.depend_de || []).includes(o.ordre)" @change="toggleDep(t, o.ordre)" /><span class="truncate">{{ o.titre }}</span></label>
                    </div></details></div>
              </div>
              <div class="flex flex-wrap items-center gap-x-5 gap-y-1 rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600">
                <span><b>Priorité</b> : {{ t.raison_priorite || '—' }}</span>
                <span class="flex items-center gap-1.5"><b>Confiance</b>
                  <span class="h-1.5 w-16 overflow-hidden rounded-full bg-slate-200"><span class="block h-full rounded-full transition-all duration-700" :class="confiance(t.niveau_confiance)" :style="{ width: t.niveau_confiance * 100 + '%' }" /></span>
                  {{ Math.round(t.niveau_confiance * 100) }} %</span>
                <span v-if="t.duree_proposee !== t.duree_estimee">Durée proposée par l'agent : {{ t.duree_proposee }} j</span>
              </div>
              <p v-if="t.source_dans_document" class="border-l-2 border-brand-300 pl-3 text-xs text-slate-500">Source : « {{ t.source_dans_document }} »</p>
              <p v-for="a in t.ambiguites" :key="a" class="flex items-start gap-1.5 text-xs text-purple-700"><Icon name="alert" :size="13" class="mt-0.5" />{{ a }}</p>
            </div>
          </Transition>
        </div>
      </li>
    </ol>

    <div class="sticky bottom-0 -mx-4 mt-6 flex flex-wrap items-center gap-3 border-t border-line bg-white/90 px-4 py-3 backdrop-blur sm:-mx-8 sm:px-8">
      <p class="text-sm text-slate-600"><b class="text-slate-900">{{ cahier.taches.length }}</b> tâches · <b class="text-slate-900">{{ totalJours }}</b> jours cumulés</p>
      <div class="ml-auto flex flex-wrap gap-2">
        <button class="btn-danger" @click="abandonner">Abandonner</button>
        <button class="btn-secondary" @click="ajouter"><Icon name="plus" :size="16" /> Ajouter une tâche</button>
        <button class="btn-primary" :disabled="!cahier.taches.length || sansMembre.length > 0" :title="sansMembre.length ? 'Affectez d\'abord un membre à chaque tâche' : ''" @click="confirm = true"><Icon name="check" :size="16" /> Valider et créer les tickets</button>
      </div>
    </div>

    <ConfirmModal :open="confirm" title="Valider ce cahier des charges ?" confirm-label="Valider et créer" :busy="validating" @confirm="valider" @cancel="confirm = false">
      <p>Le projet « <b>{{ cahier.nom_projet }}</b> » sera créé, puis <b>{{ cahier.taches.length }}</b> ticket(s) dans le CRM avec leur échéance. Les membres affectés recevront un e-mail.</p>
      <p class="mt-2 text-slate-500">Votre validation vaut autorisation : cette action ne peut pas être annulée depuis l'application.</p>
    </ConfirmModal>
  </template>
</template>
