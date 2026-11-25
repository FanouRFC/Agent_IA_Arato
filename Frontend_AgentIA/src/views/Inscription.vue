<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { post } from '@/services/api'
import { useToastStore } from '@/stores/toast'
import Icon from '@/components/Icon.vue'
import PasswordInput from '@/components/PasswordInput.vue'

const router = useRouter()
const toast = useToastStore()
const email = ref(''), mdp = ref(''), confirmation = ref(''), err = ref(''), busy = ref(false)
const imgOk = ref(true)

async function go() {
  err.value = ''
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.value.trim())) return (err.value = 'Adresse e-mail invalide.')
  if (mdp.value.length < 8) return (err.value = 'Le mot de passe doit contenir au moins 8 caractères.')
  if (mdp.value !== confirmation.value) return (err.value = 'La confirmation ne correspond pas au mot de passe.')
  busy.value = true
  try {
    await post('/auth/inscription', { email: email.value.trim(), mot_de_passe: mdp.value })
    toast.ok('Compte créé. Un responsable doit l’activer avant votre première connexion.')
    await router.push('/login')
  } catch (e: any) { err.value = e.message }
  busy.value = false
}
</script>

<template>
  <div class="theme-clair grid h-dvh overflow-hidden bg-white lg:grid-cols-2">
    <section class="relative hidden overflow-hidden bg-gradient-to-br from-[#16274B] via-[#1B3A65] to-[#4F8B89] lg:block" aria-label="Arato, l'IA au service de vos projets">
      <img v-if="imgOk" src="/login-arato.jpg" alt="Une équipe Arato consulte l'Agent IA"
        class="absolute inset-0 size-full object-cover object-center" @error="imgOk = false" />
      <div v-else class="relative flex h-full flex-col justify-center gap-3 p-10 text-white">
        <p class="text-[11px] font-semibold uppercase tracking-[0.14em] text-white/60">Arato · Agent IA</p>
        <h2 class="display text-3xl leading-tight">L'IA au service de vos projets</h2>
      </div>
    </section>

    <section class="flex items-center justify-center overflow-hidden px-3 py-3 sm:px-5">
      <form class="rise w-full max-w-sm" @submit.prevent="go">
        <div class="mb-10 flex items-center gap-3">
          <span class="grid size-10 place-items-center rounded-xl bg-azur text-white"><Icon name="sparkles" :size="19" /></span>
          <span class="display text-lg text-slate-900">Arato · Agent IA</span>
        </div>
        <p class="eyebrow">Espace responsable</p>
        <h2 class="display mt-2 text-[2.1rem] leading-tight text-slate-900">Créer un compte</h2>
        <p class="mt-2 text-sm text-slate-500">Votre compte devra être activé par un responsable avant de pouvoir vous connecter.</p>
        <span class="mt-5 block h-1 w-12 rounded-full bg-azur" aria-hidden="true" />

        <div class="mt-8 space-y-5">
          <div>
            <label class="label" for="ins-email">Adresse e-mail</label>
            <div class="relative">
              <Icon name="mail" :size="16" class="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
              <input id="ins-email" v-model="email" type="email" class="input py-2.5 pl-10" autocomplete="email" placeholder="vous@exemple.mg" autofocus required />
            </div>
          </div>
          <div>
            <label class="label" for="ins-mdp">Mot de passe</label>
            <PasswordInput id="ins-mdp" v-model="mdp" icon="lock" autocomplete="new-password" :minlength="8" placeholder="8 caractères minimum" required />
          </div>
          <div>
            <label class="label" for="ins-conf">Confirmation du mot de passe</label>
            <PasswordInput id="ins-conf" v-model="confirmation" icon="lock" autocomplete="new-password" placeholder="Répétez le mot de passe" required />
          </div>
          <p v-if="err" class="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700" role="alert"><Icon name="alert" :size="16" />{{ err }}</p>
          <button class="btn-primary press group w-full py-3 text-[15px]" :disabled="busy || !email || !mdp || !confirmation">
            {{ busy ? 'Création…' : 'Créer le compte' }}<Icon v-if="!busy" name="right" :size="16" class="transition group-hover:translate-x-0.5" />
          </button>
        </div>

        <p class="mt-8 text-xs text-slate-500">
          Déjà un compte ? <RouterLink to="/login" class="font-medium text-slate-900 underline decoration-azur decoration-2 underline-offset-4">Se connecter</RouterLink>
        </p>
      </form>
    </section>
  </div>
</template>