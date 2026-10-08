<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, fmtDate, SITUATION_CLASS, STATUT, tid } from '@/services/api'

const rows = ref<any[]>([]), statut = ref(''), retard = ref(false), err = ref('')
onMounted(async () => { try { rows.value = await api('/dashboard') } catch (e: any) { err.value = e.message } })
const shown = computed(() => rows.value.filter(r =>
  (!statut.value || r.statut === statut.value) && (!retard.value || r.situation === 'en_retard')))
const count = (s: string) => rows.value.filter(r => r.statut === s).length
</script>

<template>
  <h1 class="text-2xl font-semibold">Tableau de bord</h1>
  <p class="mt-1 text-sm text-ink/70">Le statut CRM, l'avancement déclaré et l'état de l'échéance sont distincts : « en retard » n'est jamais un statut.</p>
  <p v-if="err" class="mt-3 text-brick" role="alert">{{ err }}</p>
  <div class="mt-4 flex flex-wrap items-center gap-2 text-sm">
    <button v-for="s in Object.keys(STATUT)" :key="s" class="btn-quiet" :class="statut === s && 'bg-teal-soft!'"
      @click="statut = statut === s ? '' : s">{{ STATUT[s] }} ({{ count(s) }})</button>
    <label class="ml-2 flex items-center gap-2"><input type="checkbox" v-model="retard" /> En retard uniquement
      ({{ rows.filter(r => r.situation === 'en_retard').length }})</label>
  </div>
  <div class="mt-4 overflow-x-auto panel p-0!">
    <table class="w-full text-left text-sm">
      <thead class="border-b border-line bg-paper"><tr>
        <th class="p-3">Ticket</th><th class="p-3">Statut CRM</th><th class="p-3">Avancement déclaré</th>
        <th class="p-3">État de l'échéance</th><th class="p-3">Motif documenté</th></tr></thead>
      <tbody>
        <tr v-for="r in shown" :key="r.id" class="border-b border-line/60 align-top">
          <td class="p-3"><router-link :to="`/tickets/${r.id}`" class="font-medium text-teal underline">{{ tid(r.id) }}</router-link>
            <div class="max-w-xs text-xs text-ink/70">{{ r.titre }}</div></td>
          <td class="p-3">{{ STATUT[r.statut] }}</td>
          <td class="p-3">{{ r.avancement_declare }} %</td>
          <td class="p-3"><span class="tag" :class="SITUATION_CLASS[r.situation]">{{ r.etat_echeance }}</span>
            <div class="mt-1 text-xs text-ink/60">échéance {{ fmtDate(r.echeance) }}</div></td>
          <td class="p-3">{{ r.motif ?? (r.situation === 'en_retard' ? 'Aucun motif documenté' : '—') }}</td>
        </tr>
        <tr v-if="!shown.length"><td colspan="5" class="p-6 text-center text-ink/60">Aucun ticket ne correspond à ces filtres.</td></tr>
      </tbody>
    </table>
  </div>
</template>
