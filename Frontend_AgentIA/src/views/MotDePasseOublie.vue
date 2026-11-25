<script setup lang="ts">
import { ref } from 'vue'
import { post } from '@/services/api'
import Icon from '@/components/Icon.vue'

const email = ref(''), err = ref(''), busy = ref(false), envoye = ref(false)

async function go() {
  err.value = ''; busy.value = true
  try {
    await post('/auth/mot-de-passe-oublie', { email: email.value })
    envoye.value = true
  } catch (e: any) { err.value = e.message }
  busy.value = false
}
</script>

<template>
  <div class="theme-clair grid min-h-dvh place-items-center bg-white px-4">
    <div class="rise w-full max-w-sm">
      <div class="mb-8 flex items-center gap-3">
        <span class="grid size-10 place-items-center rounded-xl bg-azur text-white"><Icon name="sparkles" :size="19" /></span>
        <span class="display text-lg text-slate-900">Arato · Agent IA</span>
      </div>

      <template v-if="!envoye">
        <h2 class="display text-[2rem] leading-tight text-slate-900">Mot de passe oublié</h2>
        <p class="mt-2 text-sm text-slate-500">Saisissez votre adresse e-mail : nous vous enverrons un lien pour choisir un nouveau mot de passe.</p>
        <form class="mt-8 space-y-5" @submit.prevent="go">
          <div>
            <label class="label" for="email">Adresse e-mail</label>
            <div class="relative">
              <Icon name="mail" :size="16" class="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
              <input id="email" v-model="email" type="email" class="input py-2.5 pl-10" autocomplete="email" placeholder="vous@exemple.mg" autofocus required />
            </div>
          </div>
          <p v-if="err" class="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700" role="alert"><Icon name="alert" :size="16" />{{ err }}</p>
          <button class="btn-primary w-full py-3 text-[15px]" :disabled="busy || !email">{{ busy ? 'Envoi…' : 'Envoyer le lien' }}</button>
        </form>
      </template>

      <div v-else role="status">
        <span class="grid size-12 place-items-center rounded-full bg-emerald-50 text-emerald-600"><Icon name="check" :size="22" /></span>
        <h2 class="display mt-4 text-2xl text-slate-900">Vérifiez votre boîte mail</h2>
        <p class="mt-2 text-sm text-slate-500">Si un compte existe pour <b class="text-slate-700">{{ email }}</b>, un lien de réinitialisation valable 1 heure vient d'être envoyé.</p>
      </div>

      <p class="mt-8 text-center text-sm text-slate-500">
        <RouterLink to="/login" class="font-medium text-slate-900 underline decoration-azur decoration-2 underline-offset-4">Retour à la connexion</RouterLink>
      </p>
    </div>
  </div>
</template>