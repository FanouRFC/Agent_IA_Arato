<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { post } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import { useProjectStore } from '@/stores/project'
import Icon from '@/components/Icon.vue'
import PasswordInput from '@/components/PasswordInput.vue'

const router = useRouter()
const auth = useAuthStore()
const project = useProjectStore()
const email = ref(''), mdp = ref(''), err = ref(''), busy = ref(false)
const imgOk = ref(true)           // passe à false si /login-arato.jpg est absente : on affiche alors le panneau aux couleurs d'Arato

async function go() {
  err.value = ''; busy.value = true
  try {
    const r = await post('/auth/login', { email: email.value, mot_de_passe: mdp.value })
    auth.setSession(r.token, r.email)
    project.select(null)            // aucun projet par défaut : le choix se fait après le cahier des charges
    await router.push('/')
  } catch (e: any) { err.value = e.message }
  busy.value = false
}
const POINTS = [
  { ico: 'file', t: 'Du cahier des charges aux tickets', d: "L'IA propose, vous relisez et validez." },
  { ico: 'activity', t: 'Un suivi qui réagit en direct', d: 'Chaque changement du CRM met la situation à jour.' },
  { ico: 'shield', t: 'Des chiffres sûrs', d: "Les calculs sont faits par le programme, jamais par l'IA." },
]
</script>

<template>
  <div class="theme-clair grid h-dvh overflow-hidden bg-white lg:grid-cols-2">
    <!-- Visuel : moitié de l'écran. Avec photo : elle remplit le panneau. Sans photo : fond aux couleurs du logo + points clés -->
    <section class="relative hidden overflow-hidden bg-gradient-to-br from-[#16274B] via-[#1B3A65] to-[#4F8B89] lg:block" aria-label="Arato, l'IA au service de vos projets">
      <img v-if="imgOk" src="/login-arato.jpg" alt="Une équipe Arato consulte l'Agent IA : cahier des charges, validation, CRM, analyses et chat"
        class="absolute inset-0 size-full object-cover object-center" fetchpriority="high" @error="imgOk = false" />
      <div v-else class="relative flex h-full flex-col justify-center gap-8 p-10 text-white">
        <div>
          <p class="text-[11px] font-semibold uppercase tracking-[0.14em] text-white/60">Arato · Agent IA</p>
          <h2 class="display mt-3 text-3xl leading-tight">L'IA au service de vos projets</h2>
        </div>
        <ul class="grid gap-5 text-sm text-white/80">
          <li v-for="p in POINTS" :key="p.t" class="flex items-start gap-3"><Icon :name="p.ico" :size="16" class="mt-0.5 shrink-0 text-white" /><span><b class="font-semibold text-white">{{ p.t }}</b><br />{{ p.d }}</span></li>
        </ul>
      </div>
    </section>

    <!-- Formulaire : épuré, sur fond blanc -->
    <section class="flex items-center justify-center overflow-hidden px-3 py-3 sm:px-5">
      <form class="rise w-full max-w-sm" @submit.prevent="go">
        <div class="mb-10 flex items-center gap-3">
          <span class="grid size-10 place-items-center rounded-xl bg-azur text-white"><Icon name="sparkles" :size="19" /></span>
          <span class="display text-lg text-slate-900">Arato · Agent IA</span>
        </div>
        <p class="eyebrow">Espace responsable</p>
        <h2 class="display mt-2 text-[2.1rem] leading-tight text-slate-900">Connexion</h2>
        <p class="mt-2 text-sm text-slate-500">Retrouvez le suivi de vos projets : cahiers des charges, tickets, risques et recommandations de l'agent.</p>
        <span class="mt-5 block h-1 w-12 rounded-full bg-azur" aria-hidden="true" />

        <div class="mt-8 space-y-5">
          <div>
            <label class="label" for="email">Adresse e-mail</label>
            <div class="relative">
              <Icon name="mail" :size="16" class="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
              <input id="email" v-model="email" type="email" class="input py-2.5 pl-10" autocomplete="email" placeholder="vous@exemple.mg" autofocus required />
            </div>
          </div>
          <div>
            <label class="label" for="mdp">Mot de passe</label>
            <PasswordInput id="mdp" v-model="mdp" icon="lock" autocomplete="current-password" placeholder="Votre mot de passe" required />
          </div>
          <p v-if="err" class="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700" role="alert"><Icon name="alert" :size="16" />{{ err }}</p>
          <button class="btn-primary press group w-full py-3 text-[15px]" :disabled="busy || !email || !mdp">
            {{ busy ? 'Connexion…' : 'Se connecter' }}<Icon v-if="!busy" name="right" :size="16" class="transition group-hover:translate-x-0.5" />
          </button>
        </div>

        <ul class="mt-9 grid gap-2.5 border-t border-line pt-6 text-xs text-slate-500" :class="imgOk ? '' : 'lg:hidden'">
          <li v-for="p in POINTS" :key="p.t" class="flex items-start gap-2.5"><Icon :name="p.ico" :size="14" class="mt-0.5 shrink-0 text-azur" /><span><b class="font-semibold text-slate-700">{{ p.t }}</b> · {{ p.d }}</span></li>
        </ul>
        <p class="mt-6 flex items-center gap-1.5 text-xs text-slate-400"><Icon name="lock" :size="12" /> Connexion sécurisée · accès réservé aux comptes responsables</p>
        <p class="mt-2 text-xs text-slate-500">
          Équipe du CRM ? <RouterLink to="/crm" class="font-medium text-slate-900 underline decoration-azur decoration-2 underline-offset-4">Ouvrir le simulateur CRM</RouterLink>
        </p>
      </form>
    </section>
  </div>
</template>