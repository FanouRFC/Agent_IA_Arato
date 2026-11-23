<script setup lang="ts">
import { useConfirmStore } from '@/stores/confirm'
import { ref, watch } from 'vue'
import { put } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'
import PasswordInput from '@/components/PasswordInput.vue'
import Icon from '@/components/Icon.vue'
import Modal from '@/components/Modal.vue'

/** Paramètres : changement du mot de passe du compte connecté (il ne se fait plus depuis la page Compte). */
const confirmer = useConfirmStore()
const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()
const auth = useAuthStore()
const toast = useToastStore()
const mdp = ref({ ancien: '', nouveau: '', confirmation: '' })
const busy = ref(false), err = ref('')

watch(() => props.open, (v) => { if (v) { mdp.value = { ancien: '', nouveau: '', confirmation: '' }; err.value = '' } })

async function changer() {
  err.value = ''
  const m = mdp.value
  if (m.nouveau.length < 8) return (err.value = 'Le nouveau mot de passe doit contenir au moins 8 caractères.')
  if (m.nouveau !== m.confirmation) return (err.value = 'La confirmation ne correspond pas au nouveau mot de passe.')
  if (!(await confirmer.ask({ title: 'Modifier le mot de passe ?', message: 'Le nouveau mot de passe sera utilisé dès la prochaine connexion.', confirmLabel: 'Modifier' }))) return
  busy.value = true
  try {
    await put('/compte/mot-de-passe', { ancien: m.ancien, nouveau: m.nouveau })
    toast.ok('Mot de passe modifié.')
    emit('close')
  } catch (e: any) { err.value = e.message }
  busy.value = false
}
</script>

<template>
  <Modal :open="open" size="md" title="Paramètres" :subtitle="auth.email" @close="emit('close')">
    <form id="form-parametres" class="space-y-5" @submit.prevent="changer">
      <div class="flex items-center gap-3">
        <span class="grid size-10 place-items-center rounded-xl bg-brand-100 text-brand-700"><Icon name="key" :size="19" /></span>
        <div>
          <h3 class="text-sm font-semibold text-slate-900">Mot de passe</h3>
          <p class="text-xs text-slate-500">8 caractères minimum.</p>
        </div>
      </div>
      <div>
        <label class="label" for="ps-a">Mot de passe actuel</label>
        <PasswordInput id="ps-a" v-model="mdp.ancien" autocomplete="current-password" required />
      </div>
      <div class="grid gap-4 sm:grid-cols-2">
        <div>
          <label class="label" for="ps-n">Nouveau mot de passe</label>
          <PasswordInput id="ps-n" v-model="mdp.nouveau" autocomplete="new-password" :minlength="8" required />
        </div>
        <div>
          <label class="label" for="ps-c">Confirmation</label>
          <PasswordInput id="ps-c" v-model="mdp.confirmation" autocomplete="new-password" required />
        </div>
      </div>
      <p v-if="err" class="flex items-center gap-1.5 text-sm text-red-600" role="alert"><Icon name="alert" :size="14" />{{ err }}</p>
    </form>
    <template #footer>
      <button class="btn-secondary" type="button" @click="emit('close')">Annuler</button>
      <button class="btn-primary" type="submit" form="form-parametres" :disabled="busy || !mdp.ancien || !mdp.nouveau">{{ busy ? 'Enregistrement…' : 'Modifier le mot de passe' }}</button>
    </template>
  </Modal>
</template>
