<script setup lang="ts">
import { ref } from 'vue'
import Icon from '@/components/Icon.vue'

/** Champ de mot de passe avec bouton « œil » : affiche ou masque la saisie (touche Entrée et gestionnaires de mots de passe inchangés). */
withDefaults(defineProps<{ modelValue: string; id?: string; autocomplete?: string; minlength?: number; required?: boolean; placeholder?: string; icon?: string }>(),
  { autocomplete: 'current-password' })
defineEmits<{ 'update:modelValue': [string] }>()
const visible = ref(false)
</script>

<template>
  <div class="relative">
    <Icon v-if="icon" :name="icon" :size="16" class="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
    <input :id="id" :value="modelValue" :type="visible ? 'text' : 'password'" class="input py-2.5 pr-11" :class="icon && 'pl-10'" :autocomplete="autocomplete"
      :minlength="minlength" :required="required" :placeholder="placeholder" @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)" />
    <button type="button" class="absolute right-1.5 top-1/2 grid size-8 -translate-y-1/2 place-items-center rounded-lg text-slate-400 transition hover:bg-brand-50 hover:text-brand-700"
      :aria-label="visible ? 'Masquer le mot de passe' : 'Afficher le mot de passe'" :aria-pressed="visible" :title="visible ? 'Masquer le mot de passe' : 'Voir le mot de passe'"
      @click="visible = !visible">
      <Icon :name="visible ? 'eyeOff' : 'eye'" :size="17" />
    </button>
  </div>
</template>
