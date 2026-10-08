<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
const router = useRouter()
const auth = useAuthStore()
const nom = ref(''), mdp = ref(''), err = ref('')
async function go() {
  err.value = ''
  try {
    const r = await api('/auth/login', { method: 'POST', body: JSON.stringify({ nom: nom.value, mot_de_passe: mdp.value }) })
    auth.setToken(r.token)
    router.push('/')
  } catch (e: any) { err.value = e.message }
}
</script>

<template>
  <div class="mx-auto mt-24 max-w-sm panel">
    <h1 class="text-xl font-semibold">Connexion</h1>
    <p class="mt-1 text-sm text-ink/70">Espace réservé au haut responsable.</p>
    <div class="mt-5 space-y-3">
      <label class="block text-sm">Identifiant<input v-model="nom" class="field mt-1" autocomplete="username" /></label>
      <label class="block text-sm">Mot de passe
        <input v-model="mdp" type="password" class="field mt-1" autocomplete="current-password" @keyup.enter="go" /></label>
      <p v-if="err" class="text-sm text-brick" role="alert">{{ err }}</p>
      <button class="btn w-full justify-center" @click="go">Se connecter</button>
    </div>
  </div>
</template>
