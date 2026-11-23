<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api, nomAffiche, photoCompte, post, tid } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import { useProjectStore } from '@/stores/project'
import Avatar from '@/components/Avatar.vue'
import EmptyState from '@/components/EmptyState.vue'
import Icon from '@/components/Icon.vue'
import PageHeader from '@/components/PageHeader.vue'
import SituationBadge from '@/components/SituationBadge.vue'

interface Msg { role: 'moi' | 'agent'; text: string; cites?: number[]; erreur?: boolean; question?: string }
type Seg = { t: string; b?: boolean; id?: number }
type Block = { kind: 'p'; segs: Seg[] } | { kind: 'ul' | 'ol'; items: Seg[][] }

const project = useProjectStore()
const auth = useAuthStore()
// Accueil : ton d'un site professionnel, avec le nom de l'utilisateur
const salut = computed(() => (new Date().getHours() >= 18 ? 'Bonsoir' : 'Bonjour'))
const prenom = computed(() => nomAffiche(auth.email))
const q = ref(''), busy = ref(false), secondes = ref(0)
const box = ref<HTMLElement>(), input = ref<HTMLTextAreaElement>()
const msgs = ref<Msg[]>([])
const tickets = ref<Record<number, any>>({})
const exemples = ref<string[]>(['Quelles tâches sont en retard ?', 'Quelles tâches sont à surveiller ?'])
const bas = ref(true), nouveau = ref(false), copie = ref(-1)
let tour = 0, chrono: number | undefined

// ----- Chargement -----
async function chargerTickets() {
  if (!project.activeId) return
  try {
    const d = await api(`/projets/${project.activeId}/dashboard`)
    tickets.value = Object.fromEntries(d.tickets.map((t: any) => [t.id, t]))
    const tard = d.tickets.find((t: any) => t.situation === 'en_retard')
    exemples.value = ['Quelles tâches sont en retard ?', 'Quelles tâches sont à surveiller ?',
      ...(tard ? [`Pourquoi ${tid(tard.id)} est-elle en retard ?`] : [])]
  } catch { /* facultatif */ }
}

const cle = () => `chat_debut_${project.activeId}`
function lireDebut(): number {
  try { return Number(localStorage.getItem(cle()) || 0) } catch { return 0 }
}
function ecrireDebut(n: number) {
  try { localStorage.setItem(cle(), String(n)) } catch { /* stockage indisponible */ }
}
async function nouvelle() {
  if (busy.value || !project.activeId) return
  try {
    const h = await api(`/projets/${project.activeId}/chat`)
    ecrireDebut(h.length)
  } catch { /* on vide tout de même l'affichage */ }
  tour++; msgs.value = []; q.value = ''
  input.value?.focus()
}

async function load() {
  tour++; arreterChrono(); busy.value = false
  msgs.value = []; tickets.value = {}
  if (!project.activeId) return
  try {
        const h = await api(`/projets/${project.activeId}/chat`)
    if (lireDebut() > h.length) ecrireDebut(0)          // historique purgé côté serveur : on repart de zéro
    msgs.value = h.slice(lireDebut()).flatMap((c: any): Msg[] => [{ role: 'moi', text: c.question }, { role: 'agent', text: c.reponse, cites: c.tickets_cites }])
  } catch { /* l'historique est facultatif */ }
  await chargerTickets()
  await scroll(true)
}
onMounted(load)
watch(() => project.activeId, load)
onUnmounted(arreterChrono)

// ----- Défilement respectueux -----
function onScroll() {
  const el = box.value
  if (!el) return
  bas.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  if (bas.value) nouveau.value = false
}
async function scroll(force = false) {
  await nextTick()
  if (force || bas.value) { box.value?.scrollTo({ top: box.value.scrollHeight, behavior: 'smooth' }); nouveau.value = false }
  else nouveau.value = true
}

// ----- Envoi, arrêt, nouvel essai -----
function demarrerChrono() { secondes.value = 0; arreterChrono(); chrono = window.setInterval(() => secondes.value++, 1000) }
function arreterChrono() { if (chrono) clearInterval(chrono); chrono = undefined }

async function send(text = q.value, renvoi = false) {
  text = text.trim()
  if (!text || busy.value || !project.activeId) return
  const mine = ++tour
  if (!renvoi) msgs.value.push({ role: 'moi', text })
  q.value = ''; busy.value = true; demarrerChrono()
  await scroll(true)
  try {
    const r = await post(`/projets/${project.activeId}/chat`, { question: text })
    if (mine !== tour) return                       // réponse abandonnée entre-temps
    msgs.value.push({ role: 'agent', text: r.reponse, cites: r.tickets_cites })
    chargerTickets()
  } catch (e: any) {
    if (mine !== tour) return
    msgs.value.push({ role: 'agent', text: e.message || 'Une erreur est survenue.', erreur: true, question: text })
  }
  arreterChrono(); busy.value = false
  await scroll(); input.value?.focus()
}
/** Arrêter : la réponse, si elle arrive, sera ignorée (le serveur termine son calcul de son côté). */
function arreter() {
  const derniere = [...msgs.value].reverse().find((m) => m.role === 'moi')?.text ?? ''
  tour++; arreterChrono(); busy.value = false
  msgs.value.push({ role: 'agent', text: 'Réponse interrompue.', erreur: true, question: derniere })
  scroll(); input.value?.focus()
}
function reessayer(i: number) {
  const m = msgs.value[i]
  if (!m?.question) return
  msgs.value.splice(i, 1)
  send(m.question, true)
}
async function copier(i: number, text: string) {
  try {
    await navigator.clipboard.writeText(text)
    copie.value = i
    setTimeout(() => { if (copie.value === i) copie.value = -1 }, 1500)
  } catch { /* presse-papiers indisponible */ }
}

// ----- Saisie : champ qui s'agrandit, Entrée envoie, Maj+Entrée saute une ligne -----
function grow() {
  const el = input.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}
watch(q, () => nextTick(grow))
function onKey(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send() }
}

// ----- Mise en forme des réponses (gras, listes, liens vers les tickets), sans HTML brut -----
function inline(line: string): Seg[] {
  const out: Seg[] = []
  for (const part of line.split(/(\*\*[^*]+\*\*)/g).filter(Boolean)) {
    const b = /^\*\*[^*]+\*\*$/.test(part)
    const txt = b ? part.slice(2, -2) : part
    for (const p of txt.split(/(T-\d+)/g).filter(Boolean))
      out.push(/^T-\d+$/.test(p) ? { t: p, id: Number(p.slice(2)), b } : { t: p, b })
  }
  return out
}
function blocs(text: string): Block[] {
  const res: Block[] = []
  let para: { kind: 'p'; segs: Seg[] } | null = null
  let liste: { kind: 'ul' | 'ol'; items: Seg[][] } | null = null
  for (const raw of text.split('\n')) {
    const line = raw.trimEnd()
    const ul = line.match(/^\s*[-*•]\s+(.*)/), ol = line.match(/^\s*\d+[.)]\s+(.*)/)
    const item = ul ?? ol
    if (item) {
      const kind: 'ul' | 'ol' = ul ? 'ul' : 'ol'
      if (!liste || liste.kind !== kind) { liste = { kind, items: [] }; res.push(liste) }
      liste.items.push(inline(item[1] ?? ''))
      para = null
    } else if (!line.trim()) {
      para = null; liste = null
    } else if (para) {
      para.segs.push({ t: '\n' }, ...inline(line))
    } else {
      para = { kind: 'p', segs: inline(line) }; res.push(para)
      liste = null
    }
  }
  return res
}
const rendu = computed(() => msgs.value.map((m) => (m.role === 'agent' && !m.erreur ? blocs(m.text) : [])))
const lien = (s: Seg, m: Msg) => !!s.id && (!!tickets.value[s.id] || !!m.cites?.includes(s.id))
</script>

<template>
  <PageHeader title="Chat avec l'agent" :subtitle="project.active ? `Questions sur le projet « ${project.active.nom} » · réponses fondées sur les données réelles du CRM` : ''">
  <button class="btn-secondary" :disabled="busy || !msgs.length" @click="nouvelle">
    <Icon name="refresh" :size="16" /> Nouvelle conversation
  </button>
</PageHeader>
  <EmptyState v-if="project.loaded && !project.active" icon="folder" title="Aucun projet sélectionné" text="Choisissez d'abord un projet sur la page de choix du projet." />
  <template v-else>
    <div class="card relative flex h-[calc(100dvh-15rem)] min-h-[26rem] flex-col">
      <div ref="box" class="no-scrollbar flex-1 space-y-5 overflow-y-auto scroll-smooth p-5 sm:p-6" aria-live="polite" @scroll.passive="onScroll">
        <!-- Accueil : salutation personnalisée et suggestions -->
        <div v-if="!msgs.length && !busy" class="flex h-full flex-col items-center justify-center text-center">
          <span class="relative grid size-14 place-items-center rounded-2xl bg-gradient-to-br from-azur via-primary to-violet-arato text-white shadow-lg floaty"><Icon name="sparkles" :size="26" /></span>
          <h2 class="display mt-6 max-w-xl text-3xl leading-tight text-slate-900 sm:text-4xl">{{ salut }} <span class="grad-text">{{ prenom }}</span>,<br />qu'est-ce que je peux faire pour vous aujourd'hui ?</h2>
          <p class="muted mt-3 max-w-md">Je réponds à partir des données reçues concernant le projet.</p>
          <div class="mt-7 grid w-full max-w-2xl gap-3 sm:grid-cols-3">
            <button v-for="e in exemples" :key="e" class="flex items-start gap-2 rounded-2xl border border-line bg-white p-4 text-left text-sm font-medium text-slate-700 transition hover:-translate-y-0.5 hover:border-brand-300 hover:shadow-card" @click="send(e)">
              <Icon name="sparkles" :size="15" class="mt-0.5 shrink-0 text-brand-500" />{{ e }}</button>
          </div>
        </div>

        <!-- Messages -->
        <div v-for="(m, i) in msgs" :key="i" class="flex items-end gap-3" :class="m.role === 'moi' ? 'justify-end' : ''">
          <span v-if="m.role === 'agent'" class="mb-1 grid size-8 shrink-0 place-items-center rounded-full text-white"
            :class="m.erreur ? 'bg-red-500' : 'bg-gradient-to-br from-azur to-violet-arato'"><Icon :name="m.erreur ? 'alert' : 'sparkles'" :size="16" /></span>

          <div class="min-w-0" :class="m.role === 'moi' ? 'max-w-[80%]' : 'max-w-[88%]'">
            <!-- Mon message -->
            <p v-if="m.role === 'moi'" class="whitespace-pre-wrap rounded-2xl rounded-br-md bg-gradient-to-br from-brand-600 to-purple-600 px-4 py-2.5 text-[15px] leading-relaxed text-white">{{ m.text }}</p>

            <!-- Erreur ou interruption -->
            <div v-else-if="m.erreur" class="rounded-2xl rounded-bl-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
              <p class="leading-relaxed">{{ m.text }}</p>
              <button v-if="m.question" class="btn-secondary btn-sm mt-2" @click="reessayer(i)"><Icon name="refresh" :size="13" /> Réessayer</button>
            </div>

            <!-- Réponse de l'agent -->
            <template v-else>
              <div class="space-y-2.5 rounded-2xl rounded-bl-md bg-slate-100 px-4 py-3 text-[15px] leading-relaxed text-slate-800">
                <template v-for="(b, k) in rendu[i]" :key="k">
                  <p v-if="b.kind === 'p'" class="whitespace-pre-line">
                    <template v-for="(s, n) in b.segs" :key="n">
                      <RouterLink v-if="lien(s, m)" :to="`/tickets/${s.id}`" class="font-semibold text-brand-700 underline decoration-brand-300 underline-offset-2 hover:text-brand-800">{{ s.t }}</RouterLink>
                      <b v-else-if="s.b" class="font-semibold text-slate-900">{{ s.t }}</b>
                      <template v-else>{{ s.t }}</template>
                    </template>
                  </p>
                  <component :is="b.kind" v-else class="space-y-1 pl-5" :class="b.kind === 'ul' ? 'list-disc' : 'list-decimal'">
                    <li v-for="(it, n) in b.items" :key="n" class="pl-1">
                      <template v-for="(s, j) in it" :key="j">
                        <RouterLink v-if="lien(s, m)" :to="`/tickets/${s.id}`" class="font-semibold text-brand-700 underline decoration-brand-300 underline-offset-2 hover:text-brand-800">{{ s.t }}</RouterLink>
                        <b v-else-if="s.b" class="font-semibold text-slate-900">{{ s.t }}</b>
                        <template v-else>{{ s.t }}</template>
                      </template>
                    </li>
                  </component>
                </template>
              </div>

              <!-- Tickets cités : cartes avec leur situation -->
              <div v-if="m.cites?.length" class="mt-2.5">
                <p class="mb-1.5 text-xs font-medium text-slate-500">Tickets cités</p>
                <div class="grid gap-2 sm:grid-cols-2">
                  <RouterLink v-for="c in m.cites.slice(0, 6)" :key="c" :to="`/tickets/${c}`"
                    class="group flex items-center gap-3 rounded-xl border border-line bg-white p-2.5 transition hover:border-brand-300 hover:shadow-sm focus-visible:outline-2 focus-visible:outline-brand-600">
                    <div class="min-w-0 flex-1">
                      <p class="text-xs font-semibold text-brand-700">{{ tid(c) }}</p>
                      <p class="truncate text-sm text-slate-700">{{ tickets[c]?.titre ?? 'Voir l\'analyse' }}</p>
                    </div>
                    <SituationBadge v-if="tickets[c]" :situation="tickets[c].situation" :label="tickets[c].etat_echeance" />
                  </RouterLink>
                </div>
              </div>

              <button class="mt-1.5 text-xs text-slate-400 transition hover:text-slate-700" @click="copier(i, m.text)">
                {{ copie === i ? 'Copié ✓' : 'Copier' }}</button>
            </template>
          </div>

          <Avatar v-if="m.role === 'moi'" class="mb-1" :nom="auth.email" :src="photoCompte(auth.photo)" :size="32" />
        </div>

        <!-- Attente -->
        <div v-if="busy" class="flex items-center gap-3" role="status">
          <span class="grid size-8 shrink-0 place-items-center rounded-full bg-gradient-to-br from-azur to-violet-arato text-white"><Icon name="sparkles" :size="16" /></span>
          <div class="flex items-center gap-3 rounded-2xl rounded-bl-md bg-slate-100 px-4 py-3 text-sm text-slate-600">
            <span class="flex gap-1" aria-hidden="true">
              <span class="size-1.5 animate-bounce rounded-full bg-slate-400" />
              <span class="size-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:150ms]" />
              <span class="size-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:300ms]" />
            </span>
            L'agent consulte les données… <span class="tabular-nums text-slate-400">{{ secondes }} s</span>
            <span v-if="secondes >= 20" class="hidden text-slate-400 sm:inline">· la première réponse peut prendre du temps</span>
          </div>
        </div>
      </div>

      <!-- Retour en bas -->
      <button v-if="nouveau" class="absolute bottom-24 left-1/2 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full bg-slate-900 px-4 py-2 text-xs font-medium text-white shadow-lg transition hover:bg-slate-700"
        @click="scroll(true)"><Icon name="down" :size="13" /> Nouveau message</button>

      <!-- Saisie -->
      <div class="border-t border-line bg-white p-3 sm:p-4">
        <div v-if="msgs.length && !busy" class="no-scrollbar mb-2.5 flex gap-2 overflow-x-auto pb-1">
          <button v-for="e in exemples" :key="e" class="shrink-0 rounded-full border border-slate-300 bg-white px-3 py-1 text-xs text-slate-600 transition hover:border-brand-400 hover:text-brand-700" @click="send(e)">{{ e }}</button>
        </div>
        <form class="flex items-end gap-2" @submit.prevent="send()">
          <textarea ref="input" v-model="q" rows="1" class="input no-scrollbar max-h-40 min-h-[2.75rem] flex-1 resize-none leading-relaxed" placeholder="Ex. Pourquoi cette tâche est-elle en retard ?"
            aria-label="Votre question" maxlength="1000" :disabled="!project.activeId" @keydown="onKey" />
          <button v-if="busy" type="button" class="btn-secondary h-11 shrink-0" @click="arreter"><Icon name="x" :size="16" /> Arrêter</button>
          <button v-else class="btn-primary h-11 shrink-0" :disabled="q.trim().length < 2"><Icon name="send" :size="16" /><span class="sr-only sm:not-sr-only">Envoyer</span></button>
        </form>
        <p class="mt-1.5 hidden text-xs text-slate-400 sm:block">Entrée pour envoyer · Maj + Entrée pour aller à la ligne</p>
      </div>
    </div>
  </template>
</template>