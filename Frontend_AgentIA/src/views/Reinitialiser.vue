<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { post } from '@/services/api'
import { useToastStore } from '@/stores/toast'
import Icon from '@/components/Icon.vue'
import PasswordInput from '@/components/PasswordInput.vue'

const route = useRoute(), router = useRouter(), toast = useToastStore()
const jeton = computed(() => String(route.query.jeton ?? ''))
const mdp = ref(''), confirmation = ref(''), err = ref(''), busy = ref(false)
const invalide = computed(() => mdp.value.length < 8 || mdp.value !== confirmation.value)

async function go() {
  err.value = ''
  if (mdp.value !== confirmation.value) { err.value = 'Les deux mots de passe ne correspondent pas.'; return }
  busy.value = true
  try {
    await post('/auth/reinitialiser', { jeton: jeton.value, mot_de_passe: mdp.value })
    toast.ok('Mot de passe modifié. Vous pouvez vous connecter.')
    await router.push('/login')
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

      <template v-if="jeton">
        <h2 class="display text-[2rem] leading-tight text-slate-900">Nouveau mot de passe</h2>
        <p class="mt-2 text-sm text-slate-500">Choisissez un mot de passe d'au moins 8 caractères.</p>
        <form class="mt-8 space-y-5" @submit.prevent="go">
          <div>
            <label class="label" for="mdp">Nouveau mot de passe</label>
            <PasswordInput id="mdp" v-model="mdp" icon="lock" autocomplete="new-password" placeholder="Nouveau mot de passe" required />
          </div>
          <div>
            <label class="label" for="mdp2">Confirmer le mot de passe</label>
            <PasswordInput id="mdp2" v-model="confirmation" icon="lock" autocomplete="new-password" placeholder="Retapez le mot de passe" required />
          </div>
          <p v-if="err" class="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700" role="alert"><Icon name="alert" :size="16" />{{ err }}</p>
          <button class="btn-primary w-full py-3 text-[15px]" :disabled="busy || invalide">{{ busy ? 'Enregistrement…' : 'Enregistrer' }}</button>
        </form>
      </template>

      <p v-else class="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900" role="alert">
        Lien incomplet. <RouterLink to="/mot-de-passe-oublie" class="font-medium underline">Refaire une demande</RouterLink>
      </p>

      <p class="mt-8 text-center text-sm text-slate-500">
        <RouterLink to="/login" class="font-medium text-slate-900 underline decoration-azur decoration-2 underline-offset-4">Retour à la connexion</RouterLink>
      </p>
    </div>
  </div>
</template>