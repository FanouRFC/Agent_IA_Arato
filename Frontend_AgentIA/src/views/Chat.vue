<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { api } from '@/services/api'

const q = ref(''), busy = ref(false), box = ref<HTMLElement>()
const msgs = ref<{ role: 'moi' | 'agent'; text: string }[]>([])
const exemples = ['Quelles tâches sont en retard ?', 'Quelles tâches sont à surveiller ?', 'Pourquoi T-014 est-elle en retard ?']
async function send(text = q.value) {
  if (!text.trim() || busy.value) return
  msgs.value.push({ role: 'moi', text }); q.value = ''; busy.value = true
  try { msgs.value.push({ role: 'agent', text: (await api('/chat', { method: 'POST', body: JSON.stringify({ question: text }) })).reponse }) }
  catch (e: any) { msgs.value.push({ role: 'agent', text: 'Erreur : ' + e.message }) }
  busy.value = false; await nextTick(); box.value?.scrollTo({ top: box.value.scrollHeight })
}
</script>

<template>
  <h1 class="text-2xl font-semibold">Chat avec l'agent</h1>
  <p class="mt-1 text-sm text-ink/70">Les réponses reposent sur les données réelles du CRM et les calculs Python.</p>
  <div ref="box" class="panel mt-4 h-[26rem] space-y-3 overflow-y-auto">
    <div v-if="!msgs.length" class="flex flex-wrap gap-2">
      <button v-for="e in exemples" :key="e" class="btn-quiet" @click="send(e)">{{ e }}</button>
    </div>
    <div v-for="(m, i) in msgs" :key="i" :class="m.role === 'moi' ? 'text-right' : ''">
      <p class="inline-block max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 text-left text-sm"
        :class="m.role === 'moi' ? 'bg-teal text-white' : 'bg-paper'">{{ m.text }}</p>
    </div>
    <p v-if="busy" class="text-sm text-ink/60">L'agent consulte les données…</p>
  </div>
  <div class="mt-3 flex gap-2">
    <input v-model="q" class="field" placeholder="Posez une question sur les tickets ou le projet" @keyup.enter="send()" />
    <button class="btn" :disabled="busy" @click="send()">Envoyer</button>
  </div>
</template>
