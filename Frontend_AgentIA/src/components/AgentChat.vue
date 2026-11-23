<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api, nomAffiche, photoCompte, post, tid } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import { useProjectStore } from '@/stores/project'
import Avatar from '@/components/Avatar.vue'
import Icon from '@/components/Icon.vue'
import SituationBadge from '@/components/SituationBadge.vue'

/* Chat conseiller : répond aux questions, donne un avis, des conseils et des analyses proactives.
   Chaque échange est enregistré sur le serveur dans une « discussion » : l'historique des discussions précédentes reste
   consultable (panneau « Historique »), et une discussion ancienne peut être rouverte et poursuivie. */
interface Msg { role: 'moi' | 'agent'; text: string; cites?: number[]; erreur?: boolean; question?: string; shown?: number }
interface Echange { id?: number; date: string; question: string; reponse: string; conversation: string; tickets_cites?: number[] }
type Seg = { t: string; b?: boolean; id?: number }
type Block = { kind: 'p'; segs: Seg[] } | { kind: 'note'; segs: Seg[] } | { kind: 'ul' | 'ol'; items: Seg[][] }

const props = defineProps<{ expanded?: boolean }>()
const emit = defineEmits<{ (e: 'toggle'): void; (e: 'close'): void }>()
const project = useProjectStore()
const auth = useAuthStore()
const salut = computed(() => (new Date().getHours() >= 18 ? 'Bonsoir' : 'Bonjour'))
const prenom = computed(() => nomAffiche(auth.email))
const q = ref(''), busy = ref(false), secondes = ref(0)
const box = ref<HTMLElement>(), input = ref<HTMLTextAreaElement>()
const msgs = ref<Msg[]>([])
const tickets = ref<Record<number, any>>({})
const synth = ref<any>(null)
const bas = ref(true), nouveau = ref(false), copie = ref(-1)
const histOuvert = ref(false)
const tous = ref<Echange[]>([])             // tout l'historique du projet (toutes les discussions)
const convId = ref('')
let tour = 0, chrono: number | undefined

const nouvelId = () => 'c' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6)
const cleConv = () => `chat_conv_${project.activeId}`

// ───── Contexte : tickets du projet + synthèse (pour les observations proactives) ─────
async function chargerContexte() {
  if (!project.activeId) return
  try {
    const d = await api(`/projets/${project.activeId}/dashboard`)
    tickets.value = Object.fromEntries(d.tickets.map((t: any) => [t.id, t]))
  } catch { /* facultatif */ }
  try { synth.value = await api(`/projets/${project.activeId}/synthese`) } catch { /* facultatif */ }
}
const tard = computed(() => Object.values(tickets.value).find((t: any) => t.situation === 'en_retard') as any)

/** Observations de l'agent : ce qu'il remarque de lui-même, sans attendre une question. */
const observations = computed(() => {
  const o: { ic: string; k: string; txt: string; q: string }[] = []
  const s = synth.value?.synthese
  const p = s?.priorites?.[0]
  if (p) o.push({ ic: 'flag', k: 'À traiter en premier', txt: `${tid(p.id)} « ${p.titre} » : ${(p.raisons ?? []).join(', ')}.`, q: `Que me conseilles-tu de faire pour ${tid(p.id)} ?` })
  const r = (s?.risques ?? []).find((x: any) => x.risque === 'eleve') ?? s?.risques?.[0]
  if (r) o.push({ ic: 'alert', k: 'Risque anticipé', txt: `${tid(r.id)} : ${String(r.prediction ?? '').slice(0, 110)}`, q: `Quels risques anticipes-tu sur ${tid(r.id)} et que faire ?` })
  const rc = synth.value?.recommandations?.[0]
  if (rc) o.push({ ic: 'sparkles', k: 'Recommandation en attente', txt: `${tid(rc.id_ticket)} : ${String(rc.texte).slice(0, 110)}`, q: `Donne-moi ton avis sur la recommandation pour ${tid(rc.id_ticket)}.` })
  if (!o.length) o.push({ ic: 'check', k: 'Point de situation', txt: 'Rien ne demande d’attention immédiate. Souhaitez-vous mon avis d’ensemble ?', q: 'Donne-moi ton avis sur le projet.' })
  return o.slice(0, 3)
})
const capacites = computed(() => [
  { t: 'Analyser', l: ['Fais-moi un résumé de la situation.', 'Quelles tâches sont en retard ?', 'Quelles tâches sont à surveiller ?'] },
  { t: 'Conseiller', l: ['Donne-moi ton avis sur le projet.', 'Que me conseilles-tu pour tenir l’échéance ?', 'Que dois-je traiter en priorité ?'] },
  { t: 'Anticiper', l: ['Quels risques anticipes-tu ?', 'Comment est répartie la charge de l’équipe ?', ...(tard.value ? [`Pourquoi ${tid(tard.value.id)} est-elle en retard ?`] : [])] },
])
const rapides = computed(() => ['Que me conseilles-tu ?', 'Quels risques anticipes-tu ?', 'Que traiter en priorité ?', 'Donne-moi ton avis.'])

// ───── Discussions : regroupement de l'historique ─────
const conversations = computed(() => {
  const m = new Map<string, { id: string; titre: string; debut: string; fin: string; n: number }>()
  for (const e of tous.value) {
    const c = m.get(e.conversation) ?? { id: e.conversation, titre: e.question, debut: e.date, fin: e.date, n: 0 }
    c.fin = e.date; c.n++; m.set(e.conversation, c)
  }
  return [...m.values()].sort((a, b) => +new Date(b.fin) - +new Date(a.fin))
})
const jourDe = (iso: string) => {
  const j = new Date(iso); j.setHours(0, 0, 0, 0)
  const t = new Date(); t.setHours(0, 0, 0, 0)
  const n = Math.round((+t - +j) / 86400000)
  return n === 0 ? "Aujourd'hui" : n === 1 ? 'Hier' : n < 7 ? 'Cette semaine' : 'Plus ancien'
}
const groupes = computed(() => {
  const g: { l: string; items: typeof conversations.value }[] = []
  for (const c of conversations.value) {
    const l = jourDe(c.fin)
    const x = g.find((y) => y.l === l)
    x ? x.items.push(c) : g.push({ l, items: [c] })
  }
  return g
})
const heure = (iso: string) => new Date(iso).toLocaleString('fr-FR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }).replace('.', '')
const tronque = (t: string, n = 64) => (t.length > n ? t.slice(0, n - 1) + '…' : t)

function messagesDe(id: string): Msg[] {
  return tous.value.filter((e) => e.conversation === id).flatMap((c): Msg[] => [{ role: 'moi', text: c.question }, { role: 'agent', text: c.reponse, cites: c.tickets_cites }])
}
async function ouvrir(id: string) {
  if (busy.value) return
  tour++; convId.value = id; msgs.value = messagesDe(id); histOuvert.value = false
  try { sessionStorage.setItem(cleConv(), id) } catch { /* stockage indisponible */ }
  await scroll(true)
}
function nouvelle() {
  if (busy.value || !project.activeId) return
  tour++; convId.value = nouvelId(); msgs.value = []; q.value = ''; histOuvert.value = false
  try { sessionStorage.setItem(cleConv(), convId.value) } catch { /* */ }
  input.value?.focus()
}

async function recharger() {
  if (!project.activeId) return
  try { tous.value = await api(`/projets/${project.activeId}/chat`) } catch { /* l'historique est facultatif */ }
}
async function load() {
  tour++; arreterChrono(); busy.value = false
  msgs.value = []; tickets.value = {}; synth.value = null; tous.value = []
  if (!project.activeId) return
  await recharger()
  let id = ''
  try { id = sessionStorage.getItem(cleConv()) ?? '' } catch { /* */ }
  const dernier = conversations.value[0]
  if (!id && dernier && Date.now() - +new Date(dernier.fin) < 12 * 3600 * 1000) id = dernier.id    // reprise d'une discussion récente
  if (id && conversations.value.some((c) => c.id === id)) { convId.value = id; msgs.value = messagesDe(id) } else convId.value = id || nouvelId()
  chargerContexte()
  await scroll(true)
}
onMounted(load)
watch(() => project.activeId, load)
onUnmounted(arreterChrono)

// ───── Défilement respectueux ─────
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

// ───── Effet d'écriture (affichage uniquement) ─────
let frappe: number | undefined
function ecrire(i: number) {
  clearInterval(frappe)
  const m = msgs.value[i]
  if (!m) return
  const pas = Math.max(4, Math.ceil(m.text.length / 90))
  frappe = window.setInterval(() => {
    const cur = msgs.value[i]
    if (!cur || cur.shown === undefined) { clearInterval(frappe); return }
    cur.shown = Math.min(cur.text.length, cur.shown + pas)
    if (cur.shown >= cur.text.length) { cur.shown = undefined; clearInterval(frappe) }
    if (bas.value) box.value?.scrollTo({ top: box.value.scrollHeight })
  }, 22)
}
onUnmounted(() => clearInterval(frappe))
const ecrit = (m: Msg) => m.shown !== undefined
const ETAPES_IA = ['Lecture des données du projet', 'Analyse des risques, des priorités et de la charge', 'Rédaction de la réponse']
const etapeIA = computed(() => Math.min(ETAPES_IA.length - 1, Math.floor(secondes.value / 3)))

// ───── Envoi, arrêt, nouvel essai ─────
function demarrerChrono() { secondes.value = 0; arreterChrono(); chrono = window.setInterval(() => secondes.value++, 1000) }
function arreterChrono() { if (chrono) clearInterval(chrono); chrono = undefined }

async function send(text = q.value, renvoi = false) {
  text = text.trim()
  if (!text || busy.value || !project.activeId) return
  const mine = ++tour
  if (!convId.value) convId.value = nouvelId()
  try { sessionStorage.setItem(cleConv(), convId.value) } catch { /* */ }
  if (!renvoi) msgs.value.push({ role: 'moi', text })
  q.value = ''; busy.value = true; demarrerChrono()
  await scroll(true)
  try {
    const r = await post(`/projets/${project.activeId}/chat`, { question: text, conversation: convId.value })
    if (mine !== tour) return                       // réponse abandonnée entre-temps
    msgs.value.push({ role: 'agent', text: r.reponse, cites: r.tickets_cites, shown: 0 })
    ecrire(msgs.value.length - 1)
    tous.value = [...tous.value, { date: new Date().toISOString(), question: text, reponse: r.reponse, conversation: convId.value, tickets_cites: r.tickets_cites }]
    chargerContexte()
  } catch (e: any) {
    if (mine !== tour) return
    msgs.value.push({ role: 'agent', text: e.message || 'Une erreur est survenue.', erreur: true, question: text })
  }
  arreterChrono(); busy.value = false
  await scroll(); input.value?.focus()
}
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

// ───── Saisie ─────
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

// ───── Mise en forme des réponses (gras, listes, notes, liens vers les tickets), sans HTML brut ─────
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
    const note = line.match(/^_(.+)_$/)
    if (note) { res.push({ kind: 'note', segs: inline(note[1] ?? '') }); para = null; liste = null }
    else if (item) {
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
const rendu = computed(() => msgs.value.map((m) => (m.role === 'agent' && !m.erreur ? blocs(m.shown !== undefined ? m.text.slice(0, m.shown) : m.text) : [])))
const COUL: Record<string, string> = { en_retard: '#FF5A36', a_surveiller: '#F2A93B', normale: '#6A83A9', ferme: '#94A3BA' }
/** Question posée depuis la synthèse (« Demander à l'agent ») : envoyée exactement comme une saisie. */
function poser(question: string) { send(question) }
defineExpose({ poser, nouvelle, busy })
const lien = (s: Seg, m: Msg) => !!s.id && (!!tickets.value[s.id] || !!m.cites?.includes(s.id))
const histVisible = computed(() => props.expanded || histOuvert.value)
</script>

<template>
  <section class="nx-chat" :class="{ 'is-wide': expanded }" aria-label="Chat avec l'agent">
    <!-- Historique des discussions : colonne fixe en mode agrandi, tiroir sinon -->
    <template v-if="histVisible">
      <div v-if="!expanded" class="nx-voile" @click="histOuvert = false" />
      <aside class="nx-hist" :class="!expanded && 'nx-hist-tiroir'" aria-label="Historique des discussions">
        <div class="nx-hist-h"><b>Discussions</b>
          <button class="nx-ib" @click="nouvelle"><Icon name="plus" :size="14" /> Nouvelle</button></div>
        <div class="nx-hist-l">
          <p v-if="!conversations.length" class="px-3 py-6 text-center text-xs text-slate-400">Vos discussions précédentes apparaîtront ici.</p>
          <template v-for="g in groupes" :key="g.l">
            <p class="nx-hist-g">{{ g.l }}</p>
            <button v-for="c in g.items" :key="c.id" type="button" class="nx-hist-i" :class="c.id === convId && 'is-on'" @click="ouvrir(c.id)">
              <b>{{ tronque(c.titre) }}</b><span>{{ c.n }} échange{{ c.n > 1 ? 's' : '' }} · {{ heure(c.fin) }}</span>
            </button>
          </template>
        </div>
      </aside>
    </template>

    <div class="nx-chat-main">
      <header class="nx-chat-h">
        <span class="orb" :class="busy && 'orb-actif'" aria-hidden="true" />
        <div class="t">
          <p>Agent IA <span class="nx-en-ligne" title="En ligne"><i /></span></p>
          <p>{{ project.active ? `Projet « ${project.active.nom} » · données réelles du CRM` : 'Aucun projet sélectionné' }}</p>
        </div>
        <button v-if="!expanded" class="nx-ib" :class="histOuvert && 'is-on'" :aria-pressed="histOuvert" title="Historique des discussions" @click="histOuvert = !histOuvert"><Icon name="history" :size="15" /><span>Historique</span></button>
        <button class="nx-ib sq" :disabled="busy || !msgs.length" title="Nouvelle discussion" aria-label="Nouvelle discussion" @click="nouvelle"><Icon name="plus" :size="15" /></button>
        <button class="nx-ib sq nx-x-wide" :title="expanded ? 'Réduire le chat' : 'Agrandir le chat'" :aria-label="expanded ? 'Réduire le chat' : 'Agrandir le chat'" @click="emit('toggle')"><Icon :name="expanded ? 'minimize' : 'maximize'" :size="15" /></button>
        <button class="nx-ib sq nx-x-close" aria-label="Fermer le chat" @click="emit('close')"><Icon name="x" :size="15" /></button>
      </header>

      <div ref="box" class="nx-fil" aria-live="polite" @scroll.passive="onScroll">
        <!-- Accueil : observations proactives + ce que l'agent sait faire -->
        <div v-if="!msgs.length && !busy" class="nx-acc">
          <div>
            <h2>{{ salut }} <em>{{ prenom }}</em>,<br />que puis-je faire pour vous&nbsp;?</h2>
            <p class="muted mt-2">Je réponds à partir des données du projet : état, avis, conseils et analyses.</p>
          </div>
          <div v-if="observations.length" class="nx-obs">
            <p class="nx-eyebrow">Ce que je remarque</p>
            <button v-for="o in observations" :key="o.k" type="button" @click="send(o.q)">
              <span class="ic"><Icon :name="o.ic" :size="16" /></span>
              <span class="tx"><b>{{ o.k }}</b>{{ o.txt }}</span>
              <Icon name="right" :size="15" class="text-slate-300" />
            </button>
          </div>
          <div v-for="c in capacites" :key="c.t" class="nx-cap">
            <p>{{ c.t }}</p>
            <div><button v-for="e in c.l" :key="e" type="button" @click="send(e)">{{ e }}</button></div>
          </div>
        </div>

        <!-- Messages -->
        <div v-for="(m, i) in msgs" :key="i" class="nx-msg" :class="m.role === 'moi' && 'moi'">
          <template v-if="m.role === 'moi'">
            <p class="nx-bulle">{{ m.text }}</p>
            <Avatar :nom="auth.email" :src="photoCompte(auth.photo)" :size="30" class="shrink-0" />
          </template>
          <template v-else>
            <span class="orb orb-mini" :class="m.erreur && 'orb-erreur'" aria-hidden="true" />
            <div class="min-w-0 flex-1">
              <div v-if="m.erreur" class="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
                <p class="leading-relaxed">{{ m.text }}</p>
                <button v-if="m.question" class="btn-secondary btn-sm mt-2" @click="reessayer(i)"><Icon name="refresh" :size="13" /> Réessayer</button>
              </div>
              <template v-else>
                <div class="nx-rep">
                  <template v-for="(b, k) in rendu[i]" :key="k">
                    <p v-if="b.kind === 'p' || b.kind === 'note'" class="whitespace-pre-line" :class="[b.kind === 'note' && 'note', ecrit(m) && k === rendu[i]!.length - 1 && 'ecrit']">
                      <template v-for="(s, n) in b.segs" :key="n">
                        <RouterLink v-if="lien(s, m)" :to="`/tickets/${s.id}`" class="nx-lien">{{ s.t }}</RouterLink>
                        <b v-else-if="s.b">{{ s.t }}</b>
                        <template v-else>{{ s.t }}</template>
                      </template>
                    </p>
                    <component :is="b.kind" v-else :class="ecrit(m) && k === rendu[i]!.length - 1 && 'ecrit'">
                      <li v-for="(it, n) in b.items" :key="n" class="pl-1">
                        <template v-for="(s, j) in it" :key="j">
                          <RouterLink v-if="lien(s, m)" :to="`/tickets/${s.id}`" class="nx-lien">{{ s.t }}</RouterLink>
                          <b v-else-if="s.b">{{ s.t }}</b>
                          <template v-else>{{ s.t }}</template>
                        </template>
                      </li>
                    </component>
                  </template>
                </div>
                <!-- Tickets cités : cartes pleine largeur, avec un vrai bouton d'ouverture -->
                <div v-if="m.cites?.length && !ecrit(m)" class="nx-cites">
                  <p class="nx-cites-t"><Icon name="link" :size="12" /> Tâches concernées · {{ m.cites.length }}</p>
                  <RouterLink v-for="c in m.cites.slice(0, 6)" :key="c" :to="`/tickets/${c}`" class="nx-cite" :style="{ '--c': COUL[tickets[c]?.situation] ?? '#94A3BA' }">
                    <div class="min-w-0">
                      <p class="id">{{ tid(c) }}<SituationBadge v-if="tickets[c]" :situation="tickets[c].situation" :label="tickets[c].etat_echeance" /></p>
                      <p class="ti">{{ tickets[c]?.titre ?? 'Voir les détails de la tâche' }}</p>
                    </div>
                    <span class="go">Voir la tâche <Icon name="right" :size="14" /></span>
                  </RouterLink>
                </div>
                <div v-if="!ecrit(m)" class="nx-acts">
                  <button @click="copier(i, m.text)">{{ copie === i ? 'Copié ✓' : 'Copier' }}</button>
                </div>
              </template>
            </div>
          </template>
        </div>

        <!-- Attente : l'agent « réfléchit » -->
        <div v-if="busy" class="nx-msg" role="status">
          <span class="orb orb-mini orb-actif" aria-hidden="true" />
          <div class="nx-pense">
            <header><span>L'agent analyse les données</span><span class="tabular-nums text-slate-400">{{ secondes }} s</span></header>
            <ul><li v-for="(e, k) in ETAPES_IA" :key="e" :class="{ fait: k < etapeIA, en: k === etapeIA }"><i />{{ e }}</li></ul>
          </div>
        </div>
      </div>

      <button v-if="nouveau" class="nx-bas" @click="scroll(true)"><Icon name="down" :size="13" /> Nouveau message</button>

      <div class="nx-saisie">
        <div v-if="msgs.length && !busy" class="nx-pc"><button v-for="e in rapides" :key="e" type="button" @click="send(e)">{{ e }}</button></div>
        <form class="nx-form" @submit.prevent="send()">
          <textarea ref="input" v-model="q" rows="1" class="no-scrollbar" placeholder="Posez une question, demandez un avis ou un conseil…"
            aria-label="Votre question" maxlength="1000" :disabled="!project.activeId" @keydown="onKey" />
          <button v-if="busy" type="button" class="nx-send" aria-label="Arrêter" @click="arreter"><Icon name="x" :size="16" /></button>
          <button v-else class="nx-send" :disabled="q.trim().length < 2" aria-label="Envoyer"><Icon name="send" :size="16" /></button>
        </form>
        <p class="nx-aide">Entrée pour envoyer · Maj + Entrée pour aller à la ligne</p>
      </div>
    </div>
  </section>
</template>
