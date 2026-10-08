<script setup lang="ts">
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const links = [
  ['/', 'Situation'],
  ['/tableau', 'Tableau de bord'],
  ['/importer', 'Cahier des charges'],
  ['/chat', 'Chat'],
  ['/admin', 'Administration'],
] as const

async function logout() {
  auth.logout()
  await router.push('/login')
}
</script>

<template>
  <header v-if="route.name !== 'login'" class="border-b border-line bg-white">
    <div class="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-5 py-3">
      <span class="font-semibold text-teal">Agent IA · Arato</span>
      <nav class="flex flex-wrap gap-1 text-sm">
        <RouterLink
          v-for="[to, label] in links"
          :key="to"
          :to="to"
          class="rounded px-3 py-1.5 hover:bg-teal-soft"
          active-class="bg-teal-soft font-medium"
        >{{ label }}</RouterLink>
      </nav>
      <button class="btn-quiet ml-auto" @click="logout">Se déconnecter</button>
    </div>
  </header>
  <main class="mx-auto max-w-6xl px-5 py-6"><RouterView /></main>
</template>
