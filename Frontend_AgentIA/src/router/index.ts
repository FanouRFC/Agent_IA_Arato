import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useProjectStore } from '@/stores/project'

/* Trois sections dans l'application :
   · « cahier »  : Cahier des charges (global, accueil après la connexion) ;
   · « suivi »   : univers d'UN projet (tableau de bord, situation, évaluation, cahier du projet, chat, historique) ;
   · « admin »   : Administration (global : modèle d'IA, journal général, comptes, e-mails).
   La page de transition « /projets » fait le lien entre le cahier des charges et le suivi d'un projet précis. */
declare module 'vue-router' {
  interface RouteMeta {
    bare?: boolean        // pas de menu ni de barre supérieure
    public?: boolean      // accessible sans connexion
    titre?: string
    section?: 'cahier' | 'suivi' | 'admin' | 'transition'
    projet?: boolean      // exige un projet choisi sur la page de transition
  }
}

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/Login.vue'), meta: { bare: true, public: true } },
    { path: '/mot-de-passe-oublie', component: () => import('@/views/MotDePasseOublie.vue'), meta: { public: true } },
{ path: '/reinitialiser', component: () => import('@/views/Reinitialiser.vue'), meta: { public: true } },
    // Simulateur du CRM (démonstration uniquement) : les membres y travaillent sur leurs tickets
    { path: '/crm', name: 'crm', component: () => import('@/views/CrmSimulateur.vue'), meta: { bare: true, public: true } },

    // 1 · Cahier des charges (accueil après la connexion)
    { path: '/', name: 'cahiers', component: () => import('@/views/Importer.vue'), meta: { titre: 'Cahier des charges', section: 'cahier' } },
    // Page de transition : choix du projet dans lequel entrer pour la phase de suivi
    { path: '/projets', name: 'projets', component: () => import('@/views/Projets.vue'), meta: { titre: 'Choix du projet', section: 'transition' } },

    // 2 · Suivi d'un projet
    { path: '/tableau', name: 'tableau', component: () => import('@/views/Dashboard.vue'), meta: { titre: 'Tableau de bord', section: 'suivi', projet: true } },
    { path: '/situation', name: 'situation', component: () => import('@/views/Synthese.vue'), meta: { titre: 'Synthèse & chat de l\'agent', section: 'suivi', projet: true } },
    { path: '/cahier-projet', name: 'cahier-projet', component: () => import('@/views/CahierProjet.vue'), meta: { titre: 'Cahier des charges du projet', section: 'suivi', projet: true } },
    { path: '/evaluation', name: 'evaluation', component: () => import('@/views/Evaluation.vue'), meta: { titre: 'Évaluation de l\'IA', section: 'suivi', projet: true } },
    { path: '/tickets/:id', name: 'ticket', component: () => import('@/views/Ticket.vue'), meta: { titre: 'Détails sur la tâche', section: 'suivi', projet: true } },
    { path: '/chat', redirect: '/situation' },   // le chat est intégré à la synthèse de l'agent
    { path: '/historique', name: 'historique', component: () => import('@/views/Historique.vue'), meta: { titre: 'Historique du projet', section: 'suivi', projet: true } },

    // 3 · Administration (générale)
    { path: '/admin', name: 'admin', component: () => import('@/views/Admin.vue'), meta: { titre: 'Administration', section: 'admin' } },

    { path: '/cahiers', redirect: '/' },
    { path: '/importer', redirect: '/' },
    { path: '/:pathMatch(.*)*', redirect: '/' },

    { path: '/inscription', name: 'inscription', component: () => import('@/views/Inscription.vue'), meta: { bare: true, public: true } },
  ],
})

// Accès réservé au haut responsable ; le suivi exige un projet choisi sur la page de transition
router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.isAuthenticated) return { name: 'login' }
  if (to.name === 'login' && auth.isAuthenticated) return { name: 'cahiers' }
  if (to.meta.projet && !useProjectStore().activeId) return { name: 'projets' }
  if ((to.name === 'login' || to.name === 'inscription') && auth.isAuthenticated) return { name: 'cahiers' }
  return true
})

export default router
