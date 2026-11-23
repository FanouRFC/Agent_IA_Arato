<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { api, nomAffiche, photoCompte } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import { useProjectStore } from '@/stores/project'
import { useLlmStore } from '@/stores/llm'
import Avatar from '@/components/Avatar.vue'
import Icon from '@/components/Icon.vue'
import SettingsModal from '@/components/SettingsModal.vue'
import ToastHost from '@/components/ToastHost.vue'
import ConfirmHost from '@/components/ConfirmHost.vue'
import { useConfirmStore } from '@/stores/confirm'
import ThemeToggle from '@/components/ThemeToggle.vue'
import LogoArato from '@/assets/img/logo.png'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const project = useProjectStore()
const llmStore = useLlmStore()
const menuOpen = ref(false)
const settingsOpen = ref(false)
const scroller = ref<HTMLElement | null>(null)
const llm = computed(() => llmStore.info)

/* Le menu a TROIS sections :
   1. Cahier des charges (global) · 2. Suivi (un projet précis, choisi sur la page de transition) · 3. Administration (global). */
const SUIVI = [
  { to: '/tableau', label: 'Tableau de bord', icon: 'dashboard' },
  { to: '/situation', label: "Synthèse & chat de l'agent", icon: 'activity' },
  { to: '/cahier-projet', label: 'Cahier du projet', icon: 'file' },
  { to: '/evaluation', label: "Évaluation de l'IA", icon: 'target' },
  { to: '/historique', label: 'Historique', icon: 'history' },
]
const bare = computed(() => !!route.meta.bare)
const titre = computed(() => (route.meta.titre as string) ?? '')
const section = computed(() => route.meta.section ?? 'cahier')
const isActive = (to: string) => (to === '/' ? route.path === '/' : route.path.startsWith(to))
/** Rappel de contexte dans la barre supérieure : projet précis (suivi) ou portée générale (cahier, administration). */
const contexte = computed(() => {
  if (section.value === 'suivi') return project.active ? { icon: 'folder', texte: project.active.nom, role: 'Projet' } : null
  if (section.value === 'admin') return { icon: 'layers', texte: 'Administration générale', role: 'Portée' , aide: "Tous les projets et toute l'application" }
  if (section.value === 'cahier') return { icon: 'file', texte: 'Cahier des charges', role: 'Portée', aide: 'Étape globale, avant le choix du projet' }
  return null
})

async function bootstrap() {
  if (!auth.isAuthenticated) return
  await project.load()
  await llmStore.refresh()
  try { auth.photo = (await api('/compte/moi')).photo } catch { /* la photo est facultative */ }
}
let rafraichir: number | undefined
onMounted(() => {
  bootstrap()
  // La liste des projets suit le CRM (un projet supprimé disparaît d'ici quelques secondes)
  rafraichir = window.setInterval(() => { if (auth.isAuthenticated && !document.hidden) project.load() }, 4000)
})
onUnmounted(() => window.clearInterval(rafraichir))
watch(() => auth.isAuthenticated, (v) => { if (v) bootstrap() })
watch(() => route.fullPath, () => { menuOpen.value = false; scroller.value?.scrollTo({ top: 0, behavior: 'auto' }) })
// Le projet actif a disparu (supprimé dans le CRM) alors qu'on est dans son suivi : retour au choix du projet.
watch(() => [project.loaded, project.activeId, route.name], () => {
  if (route.meta.projet && project.loaded && !project.activeId) router.replace('/projets')
})

const confirmer = useConfirmStore()
async function logout() {
  if (!(await confirmer.ask({ title: 'Se déconnecter ?', message: 'Vous devrez saisir à nouveau vos identifiants pour revenir.', confirmLabel: 'Se déconnecter' }))) return
  auth.logout()
  project.select(null)
  await router.push('/login')
}
</script>

<template>
  <template v-if="bare"><RouterView /></template>
  <div v-else class="h-dvh overflow-hidden">
    <!-- Barre latérale -->
    <div v-if="menuOpen" class="fixed inset-0 z-30 bg-slate-900/50 backdrop-blur-sm lg:hidden" @click="menuOpen = false" />
    <!-- Menu latéral : fixe, 18 rem + 1 cm de large, sans défilement interne -->
    <aside class="sidebar z-40 flex-col text-slate-300 shadow-[8px_0_30px_-18px_rgb(15_33_60/0.6)] lg:flex" :class="menuOpen ? 'flex' : 'hidden'" aria-label="Menu principal">
      <div class="relative flex items-center gap-3 px-6 pb-3 pt-5">
        <span class="grid size-14 place-items-center rounded-2xl shadow-lg">
          <img :src=LogoArato alt="Arato" class="size-14 object-contain" />
        </span>
        <div class="leading-tight">
          <p class="display text-[17px] leading-none text-white">TaskPilot</p>
          <p class="mt-1 text-[11px] text-ciel">Arato · suivi intelligent</p>
        </div>
      </div>

      <nav class="menu-nav relative flex-1 px-4 pb-2" aria-label="Navigation principale">
        <!-- 1 · Cahier des charges -->
        <p class="nav-section">Cahier des charges</p>
        <RouterLink to="/" class="nav-cta" :aria-current="isActive('/') ? 'page' : undefined">
          <span class="grid size-9 shrink-0 place-items-center rounded-xl bg-white/20"><Icon name="file" :size="18" /></span>
          <span class="min-w-0 flex-1 leading-tight">
            <span class="block text-[15px] font-semibold">Cahier des charges</span>
            <span class="block truncate text-[11px] text-white/80">Déposer, relire et valider</span>
          </span>
          <Icon name="right" :size="16" class="opacity-80" />
        </RouterLink>

        <!-- 2 · Suivi (un projet précis) -->
        <p class="nav-section">Suivi</p>
        <RouterLink to="/projets" class="nav-link" :aria-current="route.name === 'projets' ? 'page' : undefined">
          <span class="nav-ico"><Icon name="grid" :size="17" /></span>
          <span class="min-w-0 flex-1 truncate">{{ project.active ? 'Changer de projet' : 'Choisir un projet' }}</span>
        </RouterLink>
        <div v-if="project.active" class="mx-1 my-1.5 rounded-xl border border-white/10 bg-white/[0.05] px-3 py-1.5">
          <p class="text-[10px] font-semibold uppercase tracking-[0.14em] text-ciel/70">Projet en cours</p>
          <p class="truncate text-[13px] font-medium text-white" :title="project.active.nom">{{ project.active.nom }}</p>
        </div>
        <ul v-if="project.activeId" class="space-y-0.5">
          <li v-for="l in SUIVI" :key="l.to">
            <RouterLink :to="l.to" class="nav-link" :aria-current="isActive(l.to) ? 'page' : undefined">
              <span class="nav-ico"><Icon :name="l.icon" :size="17" /></span>{{ l.label }}
            </RouterLink>
          </li>
        </ul>
        <p v-else class="mx-2 mt-1 text-xs leading-relaxed text-slate-400">Choisissez un projet pour accéder à son suivi.</p>

        <!-- 3 · Administration (générale) -->
        <p class="nav-section">Administration</p>
        <RouterLink to="/admin" class="nav-link" :aria-current="isActive('/admin') ? 'page' : undefined">
          <span class="nav-ico"><Icon name="sliders" :size="17" /></span>Administration
        </RouterLink>
      </nav>

      <div class="relative space-y-0.5 border-t border-white/10 p-3">
        <RouterLink v-if="auth.email" to="/admin?onglet=comptes" class="mb-1 flex items-center gap-2.5 rounded-xl bg-white/[0.06] px-3 py-1.5 text-xs text-slate-300 transition hover:bg-white/10" title="Mon compte">
          <Avatar :nom="auth.email" :src="photoCompte(auth.photo)" :size="28" />
          <span class="min-w-0 leading-tight">
            <span class="block truncate text-[13px] font-medium text-white">{{ nomAffiche(auth.email) }}</span>
            <span class="block truncate text-[11px] text-slate-400">{{ auth.email }}</span>
          </span>
        </RouterLink>
        <RouterLink to="/crm" target="_blank" class="nav-crm mb-1" title="Ouvrir le simulateur CRM dans un nouvel onglet">
          <Icon name="link" :size="15" /> <span class="flex-1">Simulateur CRM</span> <Icon name="right" :size="14" class="opacity-70" />
        </RouterLink>
        <button type="button" class="nav-link w-full !py-1.5 text-left" aria-haspopup="dialog" @click="settingsOpen = true">
          <Icon name="settings" :size="15" class="mx-2.5" /> Paramètres
        </button>
        <button class="nav-link w-full !py-1.5 text-left" @click="logout">
          <Icon name="logout" :size="15" class="mx-2.5" /> Se déconnecter
        </button>
      </div>
    </aside>

    <div class="flex h-dvh min-w-0 flex-col lg:pl-[calc(18rem+1cm)]">
      <!-- Barre supérieure : titre de la page, modèle d'IA et rappel de contexte (projet précis, ou portée générale).
           Plus aucun sélecteur de projet : le projet se choisit sur la page de transition. -->
      <header class="relative z-20 flex shrink-0 flex-wrap items-center gap-3 border-b border-line bg-surface/80 px-4 py-3 backdrop-blur-md sm:px-8 xl:px-12">
        <button class="btn-ghost -ml-2 lg:hidden" aria-label="Ouvrir le menu" @click="menuOpen = true"><Icon name="menu" /></button>
        <p class="hidden text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 sm:block">{{ titre }}</p>
        <div class="ml-auto flex flex-wrap items-center gap-3">
          <span v-if="llm" class="hidden items-center gap-1.5 rounded-full border border-line bg-white px-2.5 py-1 text-xs font-medium text-slate-600 md:inline-flex"
            title="Modèle d'IA actif">
            <span class="live-dot size-1.5 rounded-full bg-azur" />
            {{ llm.modele }}
          </span>
          <span v-if="contexte" class="inline-flex max-w-72 items-center gap-2 rounded-full border border-line bg-white px-3 py-1 text-xs font-medium text-slate-700"
            :title="contexte.aide ?? contexte.texte">
            <Icon :name="contexte.icon" :size="14" class="shrink-0 text-slate-400" />
            <span class="shrink-0 text-slate-400">{{ contexte.role }}</span>
            <span class="truncate font-semibold text-slate-900">{{ contexte.texte }}</span>
          </span>
          <RouterLink v-if="section === 'suivi' && project.active" to="/projets" class="btn-ghost btn-sm">Changer</RouterLink>
          <ThemeToggle />
        </div>
      </header>
      <div ref="scroller" class="scroller min-h-0 flex-1">
      <main class="mx-auto w-full max-w-[1680px] px-4 pb-16 pt-6 sm:px-8 xl:px-14">
        <div v-if="project.error" class="mb-4 flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">
          <Icon name="alert" :size="16" class="mt-0.5" /> {{ project.error }}
        </div>
        <RouterView :key="route.name === 'ticket' ? route.fullPath : undefined" />
      </main>
      </div>
    </div>
  </div>
  <SettingsModal :open="settingsOpen" @close="settingsOpen = false" />
  <ConfirmHost />
  <ToastHost />
</template>
