<script setup lang="ts">
import { useConfirmStore } from '@/stores/confirm'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { api, fmtDate, ilYa, post, telechargerRapport, tid } from '@/services/api'
import { usePolling } from '@/composables/usePolling'
import { useProjectStore } from '@/stores/project'
import { useToastStore } from '@/stores/toast'
import EmptyState from '@/components/EmptyState.vue'
import Icon from '@/components/Icon.vue'
import AgentChat from '@/components/AgentChat.vue'

/* « Synthèse & chat de l'agent » : à gauche la lecture de l'agent (synthèse, signaux croisés, détails par onglet),
   à droite le chat conseiller, large, avec l'historique des discussions. Aucun chiffre du tableau de bord n'est répété ici.
   La page se met à jour toute seule (toutes les 2 s) dès qu'un changement survient dans le CRM. */
const confirmer = useConfirmStore()
const project = useProjectStore()
const toast = useToastStore()
const router = useRouter()
const d = ref<any>(null), err = ref(''), menu = ref(false)
const chat = ref<InstanceType<typeof AgentChat> | null>(null)
const chatOuvert = ref(false), chatLarge = ref(false)
function demander(question: string) { chatOuvert.value = true; setTimeout(() => chat.value?.poser(question), 60) }
const deciding = ref<Set<number>>(new Set())
const now = ref(Date.now())
const majRecente = ref(false)
const nouveaux = ref<Set<string>>(new Set())
const filtreRisque = ref<'tous' | 'eleve' | 'modere'>('tous')
const onglet = ref<'priorites' | 'risques' | 'evolution' | 'reco'>('priorites')
let seq = 0, derniere = '', horloge: number | undefined, coupe: number | undefined, coupeNouveau: number | undefined

/** Une réponse plus ancienne, ou d'un autre projet, est ignorée ; sans changement de contenu, rien n'est redessiné. */
async function load() {
  const pid = project.activeId
  if (!pid) return
  const mine = ++seq
  try {
    const r = await api(`/projets/${pid}/synthese`)
    if (mine !== seq || pid !== project.activeId) return
    err.value = ''
    const empreinte = JSON.stringify(r)
    if (empreinte !== derniere) {
      const premiere = derniere === ''
      const avant = new Set<string>((d.value?.synthese?.evolutions ?? []).map((e: any) => e.t + e.txt))
      derniere = empreinte; d.value = r
      if (!premiere) {
        majRecente.value = true; clearTimeout(coupe); coupe = window.setTimeout(() => (majRecente.value = false), 3000)
        const n = new Set<string>()
        for (const e of r.synthese?.evolutions ?? []) if (!avant.has(e.t + e.txt)) n.add('e' + e.t + e.txt)
        if (n.size) { nouveaux.value = n; clearTimeout(coupeNouveau); coupeNouveau = window.setTimeout(() => (nouveaux.value = new Set()), 6000) }
      }
    }
  } catch (e: any) {
    if (mine === seq && pid === project.activeId) err.value = e.message
  }
}
usePolling(load, 2000)
watch(() => project.activeId, () => { seq++; derniere = ''; d.value = null; err.value = ''; nouveaux.value = new Set(); load() })
const surFocus = () => { if (!document.hidden) load() }
const fermerMenu = () => { menu.value = false }
onMounted(() => {
  document.addEventListener('visibilitychange', surFocus)
  document.addEventListener('click', fermerMenu)
  horloge = window.setInterval(() => (now.value = Date.now()), 5000)
})
onUnmounted(() => {
  document.removeEventListener('visibilitychange', surFocus)
  document.removeEventListener('click', fermerMenu)
  clearInterval(horloge); clearTimeout(coupe); clearTimeout(coupeNouveau)
})

const s = computed(() => d.value?.synthese)
const suivi = computed(() => d.value?.suivi)
const maj = computed(() => { void now.value; return ilYa(s.value?.date) })
const paragraphes = computed(() => (s.value?.contenu ?? '').split(/\n{1,}/).map((p: string) => p.trim()).filter(Boolean))
const nbRisque = (k: string) => (s.value?.risques ?? []).filter((r: any) => r.risque === k).length
const risquesVisibles = computed(() => (s.value?.risques ?? []).filter((r: any) => filtreRisque.value === 'tous' || r.risque === filtreRisque.value))

/** Type d'une évolution, lu sur les phrases EXACTES produites par le programme (service.py) : un motif ou un titre de tâche qui contient
 *  « retard » ou « statut » ne change donc jamais la catégorie. */
type TypeEvo = 'plus' | 'statut' | 'avancement' | 'alert' | 'calendar' | 'motif' | 'autre'
function typeDe(t: string): TypeEvo {
  if (/ (a|ont) été ajoutée?s? au projet/i.test(t)) return 'plus'
  if (/: le statut est passé de/i.test(t)) return 'statut'
  if (/: l'avancement déclaré est passé de/i.test(t)) return 'avancement'
  if (/est passée en retard|: le retard est passé de|est revenue dans les délais|est désormais à surveiller/i.test(t)) return 'alert'
  if (/: l'échéance a été déplacée/i.test(t)) return 'calendar'
  if (/: un motif a été documenté/i.test(t)) return 'motif'
  return 'autre'
}
/** Pastille d'une évolution. */
const ICONES: Record<TypeEvo, string> = { plus: 'plus', statut: 'check', avancement: 'trending', alert: 'alert', calendar: 'calendar', motif: 'file', autre: 'activity' }
const iconeEvo = (t: string) => ICONES[typeDe(t)]
const LIMITE = 5

/** Résumé structuré : une phrase d'accroche, puis des blocs aérés (retards, à surveiller, recommandations, évolutions). */
const phrases = computed(() => paragraphes.value.join(' ').split(/(?<=\.)\s+/).filter(Boolean))
const accroche = computed(() => phrases.value.find((x: string) => !/^(Depuis|Recommandation)/.test(x)) ?? '')
const action = computed(() => (phrases.value.find((x: string) => /^Recommandation/.test(x)) ?? '').replace(/^Recommandation\s*:\s*/, ''))
const rubriques = computed(() => [
  { k: 'priorites' as const, l: 'Priorités', n: s.value?.priorites?.length ?? 0, i: 'flag', h: 'Quoi traiter d\'abord', alerte: (s.value?.priorites ?? []).some((p: any) => p.situation === 'en_retard') },
  { k: 'risques' as const, l: 'Risques', n: s.value?.risques?.length ?? 0, i: 'alert', h: 'Ce qui peut déraper', alerte: (s.value?.risques ?? []).some((r: any) => r.risque === 'eleve') },
  { k: 'evolution' as const, l: 'Évolution', n: s.value?.evolutions?.length ?? 0, i: 'trending', h: 'Depuis la dernière analyse', alerte: false },
  { k: 'reco' as const, l: 'Recommandations', n: d.value?.recommandations?.length ?? 0, i: 'sparkles', h: 'À valider par vous', alerte: (d.value?.recommandations?.length ?? 0) > 0 },
])
const rubActive = computed(() => rubriques.value.find((r) => r.k === onglet.value)!)
const evoOuverts = ref<Set<string>>(new Set())
const TYPES_EVO = [['tous', 'Tout'], ['plus', 'Ajouts'], ['statut', 'Statuts'], ['avancement', 'Avancements'], ['alert', 'Retards et alertes'],
                   ['calendar', 'Échéances'], ['motif', 'Motifs'], ['autre', 'Autres']] as const
const typeEvo = ref<'tous' | TypeEvo>('tous')
const evoFiltrees = computed(() => (s.value?.evolutions ?? []).filter((e: any) => typeEvo.value === 'tous' || typeDe(e.txt) === typeEvo.value))
const nbType = (k: string) => (s.value?.evolutions ?? []).filter((e: any) => k === 'tous' || typeDe(e.txt) === k).length
// Si le type choisi n'a plus d'événement (la synthèse se met à jour toute seule), on revient à « Tout » au lieu d'afficher une liste vide
watch(() => nbType(typeEvo.value), (n) => { if (n === 0 && typeEvo.value !== 'tous') typeEvo.value = 'tous' })
const toutRisques = ref(false), toutEvolutions = ref(false)
const risquesAffiches = computed(() => (toutRisques.value ? risquesVisibles.value : risquesVisibles.value.slice(0, LIMITE)))
const evolutionsAffichees = computed(() => (toutEvolutions.value ? evoFiltrees.value : evoFiltrees.value.slice(0, LIMITE)))
const ouverts = ref<Set<string>>(new Set())
const bascule = (k: string) => { const n = new Set(ouverts.value); n.has(k) ? n.delete(k) : n.add(k); ouverts.value = n }
const longue = (t?: string) => (t?.length ?? 0) > 170
void evoOuverts

async function decide(id: number, decision: 'suivie' | 'rejetee') {
  if (deciding.value.has(id)) return
  const suivre = decision === 'suivie'
  if (!(await confirmer.ask({ title: suivre ? 'Suivre cette recommandation ?' : 'Rejeter cette recommandation ?', message: suivre ? 'Elle sera marquée comme suivie et comptera dans l\'évaluation de l\'agent.' : 'Elle sera écartée et comptera comme rejetée dans l\'évaluation de l\'agent.', confirmLabel: suivre ? 'Suivre' : 'Rejeter' }))) return
  deciding.value = new Set(deciding.value).add(id)
  try {
    await post(`/recommandations/${id}/decision`, { decision })
    if (d.value) d.value.recommandations = d.value.recommandations.filter((r: any) => r.id !== id)   // disparition immédiate
    toast.ok(decision === 'suivie' ? 'Recommandation suivie.' : 'Recommandation rejetée.')
  } catch (e: any) { toast.err(e.message) }
  const n = new Set(deciding.value); n.delete(id); deciding.value = n
  derniere = ''; load()
}

async function rapport(fmt: 'pdf' | 'xlsx') {
  menu.value = false
  try { await telechargerRapport(project.activeId!, fmt, `rapport_${d.value?.projet.nom ?? 'projet'}.${fmt}`); toast.ok(`Rapport ${fmt === 'pdf' ? 'PDF' : 'Excel'} téléchargé.`) }
  catch (e: any) { toast.err(e.message) }
}
const ouvrir = (id: number) => router.push(`/tickets/${id}`)
</script>

<template>
  <div class="nx">
    <header class="nx-head nx-in">
      <div class="min-w-0 flex-1">
        <p class="nx-eyebrow mb-2">Suivi · {{ d ? d.projet.nom : 'Projet' }}</p>
        <h1>Synthèse &amp; chat de l'agent</h1>
        <p>{{ d ? `Lecture de l'agent${d.projet.date_limite ? ' · échéance finale ' + fmtDate(d.projet.date_limite) : ''}` : '' }}</p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <span v-if="s" class="inline-flex items-center gap-2 rounded-full border border-line bg-white px-3 py-1.5 text-xs text-slate-600" role="status" aria-live="polite"
          :title="suivi?.en_cours?.length ? `${suivi.en_cours.length} tâche(s) en cours de réanalyse` : 'Toutes les tâches sont à jour'">
          <span class="live-dot size-1.5 rounded-full" :class="suivi?.en_cours?.length ? 'bg-slate-400' : 'bg-azur'" />
          <template v-if="suivi?.en_cours?.length">Réanalyse en cours…</template>
          <template v-else>En direct · <span :class="majRecente && 'font-semibold text-slate-900'">{{ majRecente ? 'mis à jour à l\'instant' : maj }}</span></template>
        </span>
        <div class="relative" @click.stop>
          <button class="btn-secondary" :disabled="!project.activeId" @click="menu = !menu"><Icon name="download" :size="16" /> Rapport <Icon name="down" :size="14" /></button>
          <div v-if="menu" class="absolute right-0 z-30 mt-1 w-44 overflow-hidden rounded-xl border border-line bg-white py-1 shadow-pop">
            <button class="block w-full px-3 py-2 text-left text-sm hover:bg-brand-50" @click="rapport('pdf')">Rapport PDF</button>
            <button class="block w-full px-3 py-2 text-left text-sm hover:bg-brand-50" @click="rapport('xlsx')">Rapport Excel</button>
          </div>
        </div>
      </div>
    </header>

    <EmptyState v-if="project.loaded && !project.projets.length" icon="folder" title="Aucun projet pour l'instant"
      text="Un projet est créé à la validation d'un cahier des charges. Déposez-en un pour démarrer le cycle de l'agent.">
      <RouterLink to="/" class="btn-primary">Déposer un cahier des charges</RouterLink>
    </EmptyState>

    <p v-else-if="err" class="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">{{ err }}</p>

    <div v-else class="nx-split" :class="chatLarge && 'is-wide'">
      <!-- ───── Colonne de lecture ───── -->
      <div v-show="!chatLarge" class="nx-col">
        <div v-if="!d" class="grid gap-5"><div class="nx-skel" style="height: 14rem" /><div class="nx-skel" style="height: 18rem" /></div>

        <div v-else-if="!s" class="nx-card nx-card-p flex items-center gap-3" role="status" aria-live="polite">
          <Icon name="refresh" :size="18" class="animate-spin text-slate-500" />
          <div><p class="text-sm font-medium text-slate-800">Évaluation automatique en cours…</p><p class="muted">La synthèse s'affichera ici dès que l'analyse du projet sera terminée.</p></div>
        </div>

        <template v-else>
          <!-- Synthèse de l'agent -->
          <section class="nx-syn nx-in" style="--i: 1" aria-labelledby="t-syn">
            <header class="nx-syn-top">
              <span class="orb" aria-hidden="true" />
              <div class="min-w-0"><h2 id="t-syn">Synthèse de l'agent</h2><p>Mise à jour {{ maj }}</p></div>
              <span class="nx-syn-badge"><i class="nx-live" />Analyse active</span>
            </header>
            <p class="nx-syn-lead">{{ accroche }}</p>
            <p v-if="action" class="nx-res-act"><Icon name="target" :size="15" /><span><b>À faire en premier</b> {{ action }}</span></p>
            <div class="nx-rub" role="tablist" aria-label="Rubriques de l'analyse">
              <button v-for="r in rubriques" :key="r.k" type="button" role="tab" class="nx-rub-b" :class="r.alerte && 'is-alerte'" :aria-selected="onglet === r.k" @click="onglet = r.k">
                <span class="nx-rub-i"><Icon :name="r.i" :size="16" /></span>
                <span class="nx-rub-n nx-num">{{ r.n }}</span>
                <span class="nx-rub-l">{{ r.l }}</span>
                <span class="nx-rub-h">{{ r.h }}</span>
              </button>
            </div>
            <div class="nx-ask">
              <span class="nx-ask-l"><Icon name="sparkles" :size="13" /> Demander à l'agent</span>
              <button type="button" @click="demander('Donne-moi ton avis sur le projet.')">Son avis</button>
              <button type="button" @click="demander('Que me conseilles-tu pour tenir l’échéance ?')">Ses conseils</button>
              <button type="button" @click="demander('Quels risques anticipes-tu ?')">Les risques à venir</button>
            </div>
          </section>

          

          <!-- Détails : priorités, risques et prédictions, évolution, recommandations -->
          <section class="nx-card nx-in" style="--i: 3" aria-label="Détails de la synthèse">
            <header class="nx-det-h nx-det-t"><span class="nx-ico"><Icon :name="rubActive.i" :size="17" /></span>
              <div><h2>{{ rubActive.l }}</h2><p>{{ rubActive.h }} · {{ rubActive.n }}</p></div></header>
            <div class="nx-det-b">
              <!-- Priorités -->
              <template v-if="onglet === 'priorites'">
                <p class="muted mb-2 mt-4">Classées par l'agent : retards, tâches bloquantes, échéances proches.</p>
                <ol v-if="s.priorites?.length">
                  <li v-for="p in s.priorites.slice(0, 6)" :key="p.id">
                    <RouterLink :to="`/tickets/${p.id}`" class="nx-lig group">
                      <span class="flex min-w-0 items-start gap-3.5"><span class="nx-rang">{{ p.rang }}</span>
                        <span class="min-w-0"><h3>{{ p.titre }}</h3>
                          <span class="sub"><span class="font-medium text-slate-400">{{ tid(p.id) }}</span><span v-for="r in (p.raisons ?? [])" :key="r" class="nx-tag">{{ r }}</span></span></span></span>
                      <Icon name="right" :size="18" class="text-slate-300 transition group-hover:translate-x-1 group-hover:text-slate-900" />
                    </RouterLink>
                  </li>
                </ol>
                <p v-else class="py-6 text-slate-500">Rien ne demande d'attention immédiate.</p>
              </template>

              <!-- Risques et prédictions -->
              <template v-else-if="onglet === 'risques'">
                <p class="muted mb-3 mt-4">Ce qui pourrait se produire si rien ne change.</p>
                <div v-if="s.risques?.length" class="nx-tabs mb-1" role="tablist" aria-label="Niveau de risque">
                  <button v-for="f in ([['tous', 'Tous', s.risques.length], ['eleve', 'Élevé', nbRisque('eleve')], ['modere', 'Modéré', nbRisque('modere')]] as const)" :key="f[0]" role="tab" type="button"
                    class="nx-tab" :aria-selected="filtreRisque === f[0]" @click="filtreRisque = f[0]">{{ f[1] }}<b>{{ f[2] }}</b></button>
                </div>
                <ul v-if="risquesVisibles.length">
                  <li v-for="r in risquesAffiches" :key="r.id" class="nx-risque">
                    <div class="nx-niv" :class="r.risque === 'eleve' ? 'hi' : 'mo'"><span aria-hidden="true"><i v-for="k in 3" :key="k" :class="k <= (r.risque === 'eleve' ? 3 : 2) && 'on'" /></span>{{ r.risque === 'eleve' ? 'Élevé' : 'Modéré' }}</div>
                    <div class="min-w-0">
                      <RouterLink :to="`/tickets/${r.id}`" class="break-anywhere text-[1.02rem] font-semibold hover:underline">{{ r.titre }} <span class="text-sm font-normal text-slate-400">· {{ tid(r.id) }}</span></RouterLink>
                      <template v-if="r.prediction">
                        <p class="break-anywhere mt-1 text-[.9375rem] leading-7 text-slate-600" :class="longue(r.prediction) && !ouverts.has('r' + r.id) && 'line-clamp-3'">{{ r.prediction }}</p>
                        <button v-if="longue(r.prediction)" type="button" class="nx-plus mr-3" @click="bascule('r' + r.id)">{{ ouverts.has('r' + r.id) ? 'Voir moins' : 'Voir plus' }}</button>
                        <button type="button" class="nx-ask-ia" @click="demander(`Pourquoi ${tid(r.id)} présente-t-elle un risque ${r.risque === 'eleve' ? 'élevé' : 'modéré'} ?`)"><Icon name="sparkles" :size="12" /> Demander à l'agent</button>
                      </template>
                    </div>
                  </li>
                </ul>
                <p v-else class="py-6 text-slate-500">{{ s.risques?.length ? 'Aucun risque à ce niveau.' : 'Aucun risque identifié pour le moment.' }}</p>
                <button v-if="risquesVisibles.length > LIMITE" type="button" class="nx-plus" @click="toutRisques = !toutRisques">{{ toutRisques ? 'Réduire la liste' : `Afficher tout (${risquesVisibles.length})` }}</button>
              </template>

              <!-- Évolution -->
              <template v-else-if="onglet === 'evolution'">
                <p class="muted mb-3 mt-4">Ce qui a changé dans le CRM depuis la dernière analyse.</p>
                <div v-if="(s.evolutions?.length ?? 0) > 0" class="mb-5 flex flex-wrap gap-2" role="group" aria-label="Filtrer les évolutions">
                  <button v-for="f in TYPES_EVO.filter((x) => nbType(x[0]) > 0 || x[0] === 'tous')" :key="f[0]" type="button" class="nx-chip" :class="typeEvo === f[0] && 'is-on'"
                    :aria-pressed="typeEvo === f[0]" @click="typeEvo = f[0]; toutEvolutions = false">{{ f[1] }} <i>{{ nbType(f[0]) }}</i></button>
                </div>
                <ol v-if="s.evolutions?.length" class="nx-evo">
                  <li v-for="(e, i) in evolutionsAffichees" :key="e.t + e.txt" :class="nouveaux.has('e' + e.t + e.txt) && 'is-new nx-flash'">
                    <span class="nx-evo-pt"><Icon :name="iconeEvo(e.txt)" :size="12" /></span>
                    <time>{{ (void now, ilYa(e.t)) }}</time>
                    <p :class="longue(e.txt) && !ouverts.has('e' + e.t + e.txt) && 'line-clamp-3'">{{ e.txt }}</p>
                    <button v-if="longue(e.txt)" type="button" class="nx-plus" @click="bascule('e' + e.t + e.txt)">{{ ouverts.has('e' + e.t + e.txt) ? 'Voir moins' : 'Voir plus' }}</button>
                  </li>
                </ol>
                <p v-else class="py-6 text-slate-500">Rien de nouveau depuis la dernière analyse.</p>
                <button v-if="evoFiltrees.length > LIMITE" type="button" class="nx-plus mt-5" @click="toutEvolutions = !toutEvolutions">{{ toutEvolutions ? 'Réduire la liste' : `Afficher tout (${evoFiltrees.length})` }}</button>
              </template>

              <!-- Recommandations : suivre ou rejeter -->
              <template v-else>
                <p class="muted mb-1 mt-4">L'agent recommande, vous décidez : une recommandation se suit ou se rejette, elle ne se modifie pas.</p>
                <TransitionGroup v-if="d.recommandations.length" tag="ul" name="liste">
                  <li v-for="r in d.recommandations" :key="r.id" class="nx-reco">
                    <div class="min-w-0">
                      <RouterLink :to="`/tickets/${r.id_ticket}`">{{ tid(r.id_ticket) }} · {{ r.titre }}</RouterLink>
                      <p class="break-anywhere">{{ r.texte }}</p>
                      <p class="mt-1 text-xs text-slate-400">{{ (void now, ilYa(r.date)) }}</p>
                    </div>
                    <div class="flex flex-wrap items-center gap-2">
                      <button class="btn-primary btn-sm" :disabled="deciding.has(r.id)" @click="decide(r.id, 'suivie')"><Icon :name="deciding.has(r.id) ? 'refresh' : 'check'" :size="14" :class="deciding.has(r.id) && 'animate-spin'" /> Suivre</button>
                      <button class="btn-secondary btn-sm" :disabled="deciding.has(r.id)" @click="decide(r.id, 'rejetee')"><Icon name="x" :size="14" /> Rejeter</button>
                      <button class="btn-ghost btn-sm" @click="demander(`Donne-moi ton avis sur la recommandation pour ${tid(r.id_ticket)}.`)"><Icon name="sparkles" :size="13" /> Demander</button>
                    </div>
                  </li>
                </TransitionGroup>
                <p v-else class="py-6 text-slate-500">Aucune recommandation en attente de décision.</p>
              </template>
            </div>
          </section>
        </template>
      </div>

      <!-- ───── Chat : large, avec l'historique des discussions ───── -->
      <aside v-if="project.activeId" class="nx-chat-wrap nx-in" :class="chatOuvert && 'is-open'" style="--i: 2">
        <AgentChat ref="chat" :expanded="chatLarge" @toggle="chatLarge = !chatLarge" @close="chatOuvert = false" />
      </aside>
    </div>

    <button v-if="project.activeId && !chatOuvert" class="nx-fab" @click="chatOuvert = true"><span class="orb orb-mini !m-0" aria-hidden="true" /> Discuter avec l'agent</button>
  </div>
</template>
