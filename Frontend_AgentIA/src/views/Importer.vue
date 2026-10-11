<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { api, tid } from '@/services/api'

const PRIORITES = ['haute', 'moyenne', 'basse']
const ETAPES = ['Déposer le document', 'Relire les tâches', 'Créer les tickets']
const EXT = ['.pdf', '.docx', '.txt', '.md']
const MAX_TACHES = 10
const BAR: Record<string, string> = { haute: 'border-l-brick', moyenne: 'border-l-ochre', basse: 'border-l-line' }

// ---------- État ----------
const projets = ref<any[]>([])
const membres = ref<any[]>([])
const nom = ref('')
const projetId = ref<number | null>(null)
const texte = ref('')
const fichier = ref<File | null>(null)
const mode = ref<'fichier' | 'texte'>('fichier')
const dragging = ref(false)

const cahier = ref<any>(null)
const bilan = ref<any>(null)
const busy = ref(false)
const err = ref('')
const saved = ref('')
const elapsed = ref(0)
const confirming = ref(false)
const confirmSuppr = ref<number | null>(null)

const ouverts = ref<Set<number>>(new Set())
const filtre = ref<'toutes' | 'verifier' | 'non_affectees'>('toutes')
const showAll = ref(false)

let tick: number | undefined
let savedTimer: number | undefined
let supprTimer: number | undefined

onMounted(async () => {
  try {
    const [p, m] = await Promise.all([api('/crm/projets'), api('/crm/membres')])
    projets.value = p
    membres.value = m
  } catch (e: any) {
    err.value = e.message
  }
})
onUnmounted(() => {
  clearInterval(tick)
  clearTimeout(savedTimer)
  clearTimeout(supprTimer)
})

// ---------- Dérivés ----------
const etape = computed(() => (bilan.value ? 3 : cahier.value ? 2 : 1))
const taches = computed<any[]>(() => cahier.value?.taches ?? [])
const membreMap = computed(() => new Map<number, any>(membres.value.map((m: any) => [m.id, m] as [number, any])))
const byOrdre = computed(() => new Map<number, any>(taches.value.map((t: any) => [t.ordre, t] as [number, any])))

const locked = (t: any) => !!t.id_ticket_crm
const aVerifier = (t: any) =>
  t.origine !== 'manuel' && ((t.niveau_confiance ?? 1) < 0.6 || (t.ambiguites ?? []).length > 0)
const nonAffectee = (t: any) => !(t.membre_ids ?? []).length

const aCreer = computed(() => taches.value.filter(t => !locked(t)))
const nbVerifier = computed(() => aCreer.value.filter(aVerifier).length)
const nbNonAffectees = computed(() => aCreer.value.filter(nonAffectee).length)
const charge = computed(() => aCreer.value.reduce((n, t) => n + (Number(t.duree_estimee) || 0), 0))
const nbMembres = computed(() => new Set(aCreer.value.flatMap(t => t.membre_ids ?? [])).size)

const filtrees = computed(() => {
  if (filtre.value === 'verifier') return taches.value.filter(aVerifier)
  if (filtre.value === 'non_affectees') return taches.value.filter(t => nonAffectee(t) && !locked(t))
  return taches.value
})
const visibles = computed(() => (showAll.value ? filtrees.value : filtrees.value.slice(0, MAX_TACHES)))

const canAnalyse = computed(
  () => !!nom.value.trim() && projetId.value !== null &&
    (mode.value === 'fichier' ? !!fichier.value : texte.value.trim().length >= 30),
)
const mmss = computed(() => `${Math.floor(elapsed.value / 60)}:${String(elapsed.value % 60).padStart(2, '0')}`)

// ---------- Outils d'affichage ----------
function flash(m: string) {
  saved.value = m
  clearTimeout(savedTimer)
  savedTimer = window.setTimeout(() => (saved.value = ''), 2500)
}
const taille = (f: File) => (f.size > 1048576 ? `${(f.size / 1048576).toFixed(1)} Mo` : `${Math.max(1, Math.round(f.size / 1024))} Ko`)
const has = (t: any, id: number) => (t.membre_ids ?? []).includes(id)
const estReco = (t: any, m: any) =>
  !!t.profil_recommande && String(m.profil ?? '').toLowerCase() === String(t.profil_recommande).toLowerCase()
const membresTries = (t: any) => [...membres.value].sort((a, b) => Number(estReco(t, b)) - Number(estReco(t, a)))
const nomsMembres = (t: any) =>
  (t.membre_ids ?? []).map((i: number) => membreMap.value.get(i)?.nom).filter(Boolean).join(', ')
const depLabel = (o: number) => byOrdre.value.get(o)?.titre ?? 'tâche supprimée'
const pct = (t: any) => Math.round((t.niveau_confiance ?? 0) * 100)
const confClass = (t: any) => (pct(t) >= 70 ? 'bg-teal' : pct(t) >= 40 ? 'bg-ochre' : 'bg-brick')

function toggleOuvert(id: number) {
  const s = new Set(ouverts.value)
  s.has(id) ? s.delete(id) : s.add(id)
  ouverts.value = s
}
function toutDeplier(ouvrir: boolean) {
  ouverts.value = ouvrir ? new Set(visibles.value.map(t => t.id)) : new Set()
}

// ---------- Dépôt ----------
function pickFile(f: File | null) {
  if (!f) return
  const ext = f.name.includes('.') ? f.name.slice(f.name.lastIndexOf('.')).toLowerCase() : ''
  if (!EXT.includes(ext)) {
    err.value = 'Formats acceptés : PDF, Word (.docx), texte (.txt, .md).'
    return
  }
  err.value = ''
  fichier.value = f
}
const onPick = (e: Event) => pickFile((e.target as HTMLInputElement).files?.[0] ?? null)
function onDrop(e: DragEvent) {
  dragging.value = false
  pickFile(e.dataTransfer?.files?.[0] ?? null)
}

async function analyser() {
  err.value = ''
  busy.value = true
  elapsed.value = 0
  tick = window.setInterval(() => elapsed.value++, 1000)
  const f = new FormData()
  f.append('projet_nom', nom.value.trim())
  f.append('crm_projet_id', String(projetId.value))
  if (mode.value === 'fichier' && fichier.value) f.append('fichier', fichier.value)
  else f.append('texte', texte.value)
  try {
    cahier.value = await api('/cahiers', { method: 'POST', body: f })
    ouverts.value = new Set()
    filtre.value = 'toutes'
    showAll.value = false
  } catch (e: any) {
    err.value = e.message
  } finally {
    busy.value = false
    clearInterval(tick)
  }
}

// ---------- Relecture ----------
async function save(t: any) {
  t.duree_estimee = Math.max(1, Math.floor(Number(t.duree_estimee)) || 1)
  try {
    await api(`/taches/${t.id}`, {
      method: 'PUT',
      body: JSON.stringify({
        titre: t.titre, description: t.description, priorite: t.priorite,
        duree_estimee: t.duree_estimee, membre_ids: t.membre_ids,
      }),
    })
    flash('Modification enregistrée')
  } catch (e: any) {
    err.value = e.message
  }
}

function toggleMembre(t: any, id: number) {
  const cur: number[] = t.membre_ids ?? []
  t.membre_ids = cur.includes(id) ? cur.filter(x => x !== id) : [...cur, id]
  save(t)
}

async function remove(t: any) {
  if (confirmSuppr.value !== t.id) {
    confirmSuppr.value = t.id
    clearTimeout(supprTimer)
    supprTimer = window.setTimeout(() => (confirmSuppr.value = null), 4000)
    return
  }
  confirmSuppr.value = null
  try {
    await api(`/taches/${t.id}`, { method: 'DELETE' })
    cahier.value.taches = cahier.value.taches.filter((x: any) => x.id !== t.id)
    // Les autres tâches ne doivent plus dépendre de la tâche supprimée (sinon la validation échoue)
    for (const x of cahier.value.taches) {
      if ((x.depend_de ?? []).includes(t.ordre)) {
        x.depend_de = x.depend_de.filter((d: number) => d !== t.ordre)
        await api(`/taches/${x.id}`, { method: 'PUT', body: JSON.stringify({ depend_de: x.depend_de }) })
      }
    }
    flash('Tâche supprimée')
  } catch (e: any) {
    err.value = e.message
  }
}

async function ajouter() {
  try {
    const t = await api(`/cahiers/${cahier.value.id}/taches`, {
      method: 'POST', body: JSON.stringify({ titre: 'Nouvelle tâche', duree_estimee: 1 }),
    })
    cahier.value.taches.push(t)
    filtre.value = 'toutes'
    showAll.value = true
    ouverts.value = new Set([...ouverts.value, t.id])
    await nextTick()
    const el = document.getElementById(`titre-${t.id}`) as HTMLInputElement | null
    el?.focus()
    el?.select()
  } catch (e: any) {
    err.value = e.message
  }
}

// ---------- Validation ----------
async function valider() {
  confirming.value = false
  err.value = ''
  busy.value = true
  try {
    bilan.value = await api(`/cahiers/${cahier.value.id}/valider`, { method: 'POST' })
  } catch (e: any) {
    err.value = e.message
  } finally {
    busy.value = false
  }
}
async function retourBrouillon() {
  try {
    cahier.value = await api(`/cahiers/${cahier.value.id}`)
    bilan.value = null
  } catch (e: any) {
    err.value = e.message
  }
}
function recommencer() {
  cahier.value = null
  bilan.value = null
  nom.value = ''
  projetId.value = null
  texte.value = ''
  fichier.value = null
  err.value = ''
}
</script>

<template>
  <div class="flex flex-wrap items-center gap-x-6 gap-y-3">
    <h1 class="text-2xl font-semibold">Cahier des charges</h1>
    <ol class="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm" aria-label="Étapes">
      <li v-for="(label, i) in ETAPES" :key="label" class="flex items-center gap-2"
          :aria-current="etape === i + 1 ? 'step' : undefined">
        <span class="grid h-6 w-6 place-items-center rounded-full text-xs font-semibold"
              :class="etape > i + 1 ? 'bg-teal text-white' : etape === i + 1 ? 'bg-ink text-white' : 'bg-line/60 text-ink/60'">
          {{ etape > i + 1 ? '✓' : i + 1 }}
        </span>
        <span :class="etape === i + 1 ? 'font-semibold' : 'text-ink/60'">{{ label }}</span>
        <span v-if="i < ETAPES.length - 1" class="mx-1 h-px w-6 bg-line" aria-hidden="true"></span>
      </li>
    </ol>
  </div>

  <div v-if="err" class="panel mt-4 flex items-start gap-3 border-l-4 border-l-brick" role="alert">
    <p class="flex-1 text-sm text-brick">{{ err }}</p>
    <button class="text-sm text-ink/60 hover:underline" @click="err = ''">Fermer</button>
  </div>

  <!-- ÉTAPE 3 : bilan -->
  <section v-if="bilan" class="panel mt-5 max-w-3xl">
    <h2 class="text-lg font-semibold">
      {{ bilan.erreurs.length ? 'Création terminée avec des erreurs' : 'Tickets créés' }}
    </h2>
    <p class="mt-2">
      <strong>{{ bilan.tickets_crees }}</strong> ticket(s) créé(s) dans le CRM. Les membres affectés ont été notifiés par e-mail.
    </p>
    <div v-if="bilan.erreurs.length" class="mt-3 rounded-lg border-l-4 border-l-brick bg-brick-soft/40 px-4 py-3">
      <p class="text-sm font-medium text-brick">{{ bilan.erreurs.length }} tâche(s) n'ont pas pu être créées</p>
      <ul class="mt-1 list-disc pl-5 text-sm"><li v-for="e in bilan.erreurs" :key="e">{{ e }}</li></ul>
    </div>
    <div class="mt-4 flex flex-wrap gap-2">
      <button v-if="bilan.erreurs.length" class="btn" @click="retourBrouillon">Revenir au brouillon</button>
      <button class="btn-quiet" @click="recommencer">Déposer un autre cahier</button>
    </div>
  </section>

  <!-- ÉTAPE 1 : dépôt -->
  <section v-else-if="!cahier" class="panel mt-5 max-w-3xl">
    <p class="text-sm text-ink/70">
      Déposez le cahier des charges du chef de projet. L'agent propose des tâches, mais aucun ticket n'est créé avant votre validation.
    </p>

    <fieldset :disabled="busy" class="mt-4 min-w-0 space-y-5">
      <div class="grid gap-4 sm:grid-cols-2">
        <label class="block text-sm font-medium">Nom du projet
          <input v-model="nom" class="field mt-1 font-normal" placeholder="Ex. Refonte du portail client" />
        </label>
        <label class="block text-sm font-medium">Projet du CRM
          <select v-model="projetId" class="field mt-1 font-normal">
            <option :value="null" disabled>Choisir un projet…</option>
            <option v-for="p in projets" :key="p.id" :value="p.id">{{ p.nom }}</option>
          </select>
        </label>
      </div>

      <div>
        <div class="inline-flex rounded-lg border border-line p-0.5 text-sm" role="group" aria-label="Source du document">
          <button type="button" class="rounded-md px-3 py-1.5 transition"
                  :class="mode === 'fichier' ? 'bg-ink text-white' : 'text-ink/70 hover:text-ink'"
                  :aria-pressed="mode === 'fichier'" @click="mode = 'fichier'">Importer un fichier</button>
          <button type="button" class="rounded-md px-3 py-1.5 transition"
                  :class="mode === 'texte' ? 'bg-ink text-white' : 'text-ink/70 hover:text-ink'"
                  :aria-pressed="mode === 'texte'" @click="mode = 'texte'">Coller du texte</button>
        </div>

        <label v-if="mode === 'fichier'"
               class="mt-3 flex cursor-pointer flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed px-4 py-8 text-center transition focus-within:outline-2 focus-within:outline-teal"
               :class="dragging ? 'border-teal bg-teal-soft/40' : 'border-line hover:border-ink/40'"
               @dragover.prevent="dragging = true" @dragleave="dragging = false" @drop.prevent="onDrop">
          <input type="file" accept=".pdf,.docx,.txt,.md" class="sr-only" @change="onPick" />
          <template v-if="fichier">
            <span class="font-medium">{{ fichier.name }}</span>
            <span class="text-xs text-ink/60">{{ taille(fichier) }} · cliquez pour changer de fichier</span>
          </template>
          <template v-else>
            <span class="font-medium">Glissez le fichier ici ou cliquez pour le choisir</span>
            <span class="text-xs text-ink/60">PDF, Word (.docx) ou texte (.txt, .md)</span>
          </template>
        </label>

        <div v-else class="mt-3">
          <textarea v-model="texte" rows="8" class="field" aria-label="Texte du cahier des charges"
                    placeholder="Collez ici le contenu du cahier des charges…"></textarea>
          <p class="mt-1 text-xs" :class="texte.trim().length >= 30 ? 'text-ink/60' : 'text-ochre'">
            {{ texte.trim().length }} caractères · 30 minimum
          </p>
        </div>
      </div>
    </fieldset>

    <div class="mt-5 flex flex-wrap items-center gap-3">
      <button class="btn" :disabled="busy || !canAnalyse" @click="analyser">
        {{ busy ? 'Analyse en cours…' : 'Analyser le document' }}
      </button>
      <p v-if="!busy && !canAnalyse" class="text-xs text-ink/60">Renseignez le nom, le projet et le document.</p>
    </div>

    <div v-if="busy" class="mt-5 flex items-start gap-3 rounded-lg bg-line/30 px-4 py-3" role="status">
      <svg class="mt-0.5 h-5 w-5 shrink-0 animate-spin text-teal" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="3" opacity=".25" />
        <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" stroke-width="3" stroke-linecap="round" />
      </svg>
      <div class="text-sm">
        <p class="font-medium">L'agent analyse le document · {{ mmss }}</p>
        <p class="mt-0.5 text-ink/70">
          Il lit le cahier, le décompose en tâches, vérifie les dépendances et la cohérence, puis produit un brouillon.
          Avec un modèle local, cela peut prendre une à deux minutes. Gardez cette page ouverte.
        </p>
      </div>
    </div>
  </section>

  <!-- ÉTAPE 2 : relecture -->
  <template v-else>
    <section class="panel mt-5">
      <div class="flex flex-wrap items-end gap-x-8 gap-y-3">
        <div>
          <p class="text-3xl font-semibold leading-none tabular-nums">{{ aCreer.length }}</p>
          <p class="mt-1 text-sm text-ink/70">tâche(s) à créer</p>
        </div>
        <div>
          <p class="text-3xl font-semibold leading-none tabular-nums" :class="nbVerifier ? 'text-ochre' : ''">{{ nbVerifier }}</p>
          <p class="mt-1 text-sm text-ink/70">à vérifier</p>
        </div>
        <div>
          <p class="text-3xl font-semibold leading-none tabular-nums" :class="nbNonAffectees ? 'text-ochre' : ''">{{ nbNonAffectees }}</p>
          <p class="mt-1 text-sm text-ink/70">sans responsable</p>
        </div>
        <div>
          <p class="text-3xl font-semibold leading-none tabular-nums">{{ charge }}</p>
          <p class="mt-1 text-sm text-ink/70">jours ouvrés cumulés</p>
        </div>
      </div>
      <p class="mt-4 text-sm text-ink/70">
        Ce brouillon est proposé par l'IA. Ouvrez une tâche pour la modifier, puis validez : les tickets ne sont créés qu'à ce moment-là.
      </p>
    </section>

    <details v-if="(cahier.ambiguites ?? []).length" class="panel mt-3 border-l-4 border-l-ochre"
             :open="cahier.ambiguites.length <= 3">
      <summary class="cursor-pointer font-semibold">
        Ambiguïtés et informations manquantes ({{ cahier.ambiguites.length }})
      </summary>
      <ul class="mt-2 list-disc space-y-1 pl-5 text-sm"><li v-for="a in cahier.ambiguites" :key="a">{{ a }}</li></ul>
    </details>

    <div class="mt-5 flex flex-wrap items-center gap-2">
      <button v-for="f in [
        { k: 'toutes', l: `Toutes (${taches.length})` },
        { k: 'verifier', l: `À vérifier (${taches.filter(aVerifier).length})` },
        { k: 'non_affectees', l: `Sans responsable (${nbNonAffectees})` },
      ]" :key="f.k" type="button" class="rounded-full border px-3 py-1 text-sm transition"
              :class="filtre === f.k ? 'border-ink bg-ink text-white' : 'border-line hover:border-ink/40'"
              :aria-pressed="filtre === f.k" @click="filtre = f.k as typeof filtre; showAll = false">{{ f.l }}</button>
      <span class="ml-auto flex gap-3 text-sm">
        <button class="text-teal hover:underline" @click="toutDeplier(true)">Tout déplier</button>
        <button class="text-teal hover:underline" @click="toutDeplier(false)">Tout replier</button>
      </span>
    </div>

    <p v-if="!visibles.length" class="mt-4 text-ink/70">Aucune tâche dans ce filtre.</p>

    <article v-for="t in visibles" :key="t.id" class="panel mt-3 border-l-4 !p-0" :class="BAR[t.priorite]">
      <div class="flex flex-wrap items-center gap-2 px-3 py-3">
        <button type="button" class="grid h-8 w-8 place-items-center rounded hover:bg-line/50"
                :aria-expanded="ouverts.has(t.id)" :aria-label="ouverts.has(t.id) ? 'Replier la tâche' : 'Déplier la tâche'"
                @click="toggleOuvert(t.id)">
          <svg class="h-4 w-4 transition-transform" :class="ouverts.has(t.id) ? 'rotate-90' : ''" viewBox="0 0 24 24"
               fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="m9 6 6 6-6 6" />
          </svg>
        </button>
        <span class="text-xs font-semibold tabular-nums text-ink/50">#{{ t.ordre }}</span>
        <input :id="`titre-${t.id}`" v-model="t.titre" :disabled="locked(t)" aria-label="Titre"
               class="field min-w-48 flex-1 border-transparent! bg-transparent! font-medium! hover:border-line! focus:border-teal!"
               @change="save(t)" />
        <select v-model="t.priorite" :disabled="locked(t)" class="field w-28!" aria-label="Priorité" @change="save(t)">
          <option v-for="p in PRIORITES" :key="p">{{ p }}</option>
        </select>
        <label class="flex items-center gap-1 text-sm text-ink/80">
          <input v-model.number="t.duree_estimee" type="number" min="1" :disabled="locked(t)" class="field w-16!"
                 aria-label="Durée en jours ouvrés" @change="save(t)" /> j
        </label>
      </div>

      <div class="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 pb-3 pl-14 text-xs">
        <span v-if="locked(t)" class="rounded bg-teal-soft px-1.5 py-0.5 font-medium text-teal">Ticket {{ tid(t.id_ticket_crm) }} créé</span>
        <span v-if="t.origine === 'manuel'" class="rounded bg-line/60 px-1.5 py-0.5 text-ink/70">Ajoutée manuellement</span>
        <span v-else-if="aVerifier(t)" class="rounded bg-ochre-soft px-1.5 py-0.5 font-medium text-ochre">À vérifier</span>
        <span v-if="nonAffectee(t) && !locked(t)" class="rounded bg-ochre-soft px-1.5 py-0.5 font-medium text-ochre">Sans responsable</span>
        <span v-else-if="nomsMembres(t)" class="text-ink/70">Affectée à {{ nomsMembres(t) }}</span>
        <span v-if="(t.depend_de ?? []).length" class="text-ink/60">Après {{ t.depend_de.map((d: number) => '#' + d).join(', ') }}</span>
      </div>

      <div v-if="ouverts.has(t.id)" class="space-y-4 border-t border-line px-4 py-4">
        <label class="block text-sm font-medium">Description
          <textarea v-model="t.description" rows="3" :disabled="locked(t)" class="field mt-1 font-normal" @change="save(t)"></textarea>
        </label>

        <div v-if="(t.criteres_acceptation ?? []).length">
          <p class="text-sm font-medium">Critères d'acceptation</p>
          <ul class="mt-1 list-disc space-y-0.5 pl-5 text-sm text-ink/90"><li v-for="c in t.criteres_acceptation" :key="c">{{ c }}</li></ul>
        </div>

        <div v-if="(t.depend_de ?? []).length">
          <p class="text-sm font-medium">Doit commencer après</p>
          <ul class="mt-1 space-y-0.5 text-sm text-ink/90">
            <li v-for="d in t.depend_de" :key="d"><span class="font-semibold tabular-nums">#{{ d }}</span> {{ depLabel(d) }}</li>
          </ul>
        </div>

        <div v-if="t.origine !== 'manuel'" class="grid gap-3 text-sm sm:grid-cols-2">
          <div>
            <p class="font-medium">Priorité</p>
            <p class="text-ink/80">{{ t.raison_priorite || 'Aucune raison fournie.' }}</p>
          </div>
          <div>
            <p class="font-medium">Confiance de l'IA</p>
            <p class="mt-1 flex items-center gap-2 text-ink/80">
              <span class="h-1.5 w-24 overflow-hidden rounded-full bg-line" aria-hidden="true">
                <span class="block h-full rounded-full" :class="confClass(t)" :style="{ width: pct(t) + '%' }"></span>
              </span>
              {{ pct(t) }} %
              <span v-if="t.profil_recommande" class="text-ink/60">· profil recommandé : {{ t.profil_recommande }}</span>
            </p>
          </div>
        </div>

        <blockquote v-if="t.source_dans_document" class="border-l-2 border-line pl-3 text-sm italic text-ink/70">
          <span class="not-italic font-medium text-ink/80">Extrait du document : </span>« {{ t.source_dans_document }} »
        </blockquote>

        <div v-if="(t.ambiguites ?? []).length" class="rounded-lg bg-ochre-soft/40 px-3 py-2">
          <p class="text-sm font-medium text-ochre">À clarifier</p>
          <ul class="mt-1 list-disc pl-5 text-sm"><li v-for="a in t.ambiguites" :key="a">{{ a }}</li></ul>
        </div>

        <div>
          <p class="text-sm font-medium">Affectation <span class="font-normal text-ink/60">(un ou plusieurs membres)</span></p>
          <div class="mt-2 flex flex-wrap gap-2">
            <button v-for="m in membresTries(t)" :key="m.id" type="button" :disabled="locked(t)"
                    class="rounded-full border px-3 py-1 text-sm transition focus-visible:outline-2 focus-visible:outline-teal"
                    :class="has(t, m.id) ? 'border-teal bg-teal-soft font-medium text-teal' : 'border-line hover:border-ink/40'"
                    :aria-pressed="has(t, m.id)" @click="toggleMembre(t, m.id)">
              {{ m.nom }} <span class="text-xs opacity-70">· {{ m.profil }}</span>
              <span v-if="estReco(t, m)" class="ml-1 text-xs">(profil recommandé)</span>
            </button>
          </div>
        </div>

        <div v-if="!locked(t)" class="flex justify-end">
          <button type="button" class="text-sm hover:underline"
                  :class="confirmSuppr === t.id ? 'font-semibold text-brick' : 'text-ink/60'" @click="remove(t)">
            {{ confirmSuppr === t.id ? 'Confirmer la suppression' : 'Supprimer cette tâche' }}
          </button>
        </div>
      </div>
    </article>

    <button v-if="filtrees.length > MAX_TACHES" class="mt-3 text-sm font-medium text-teal underline-offset-2 hover:underline"
            :aria-expanded="showAll" @click="showAll = !showAll">
      {{ showAll ? 'Réduire' : `Voir les ${filtrees.length - MAX_TACHES} autres tâches` }}
    </button>

    <!-- Barre d'action -->
    <div class="panel sticky bottom-4 z-10 mt-6 flex flex-wrap items-center gap-3 shadow-lg">
      <template v-if="!confirming">
        <p class="min-w-0 flex-1 text-sm text-ink/70" aria-live="polite">
          {{ saved || `${aCreer.length} ticket(s) prêt(s) à créer` }}
        </p>
        <button class="btn-quiet" :disabled="busy" @click="ajouter">Ajouter une tâche</button>
        <button class="btn" :disabled="busy || !aCreer.length" @click="confirming = true">
          {{ busy ? 'Création…' : 'Valider et créer les tickets' }}
        </button>
      </template>
      <template v-else>
        <p class="min-w-0 flex-1 text-sm">
          Créer <strong>{{ aCreer.length }}</strong> ticket(s) dans le CRM et notifier <strong>{{ nbMembres }}</strong> membre(s) par e-mail ?
          <span v-if="nbNonAffectees" class="text-ochre">{{ nbNonAffectees }} tâche(s) n'ont pas de responsable.</span>
        </p>
        <button class="btn-quiet" @click="confirming = false">Annuler</button>
        <button class="btn" @click="valider">Confirmer</button>
      </template>
    </div>
  </template>
</template>
