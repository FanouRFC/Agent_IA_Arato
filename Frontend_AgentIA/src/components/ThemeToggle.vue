<script setup lang="ts">
import { useThemeStore } from '@/stores/theme'
import Icon from '@/components/Icon.vue'
const theme = useThemeStore()
</script>
<template>
  <button type="button" class="theme-toggle" :aria-pressed="theme.dark" :title="theme.dark ? 'Passer en mode clair' : 'Passer en mode sombre'"
    :aria-label="theme.dark ? 'Passer en mode clair' : 'Passer en mode sombre'" @click="theme.toggle()">
    <span class="theme-knob" :class="theme.dark && 'is-dark'"><Icon :name="theme.dark ? 'moon' : 'sun'" :size="13" /></span>
  </button>
</template>
<style scoped>
.theme-toggle { position: relative; display: inline-flex; align-items: center; width: 3.1rem; height: 1.7rem; padding: 0 .2rem; border: 1px solid var(--color-line); border-radius: 9999px; background: var(--card); transition: background .25s ease, border-color .25s ease; cursor: pointer; }
.theme-toggle:hover { border-color: var(--color-slate-300); }
.theme-knob { display: grid; place-items: center; width: 1.25rem; height: 1.25rem; border-radius: 9999px; background: #0A182C; color: #fff; transition: transform .28s cubic-bezier(.2,.8,.2,1), background .25s ease, color .25s ease; }
.theme-knob.is-dark { transform: translateX(1.4rem); background: #E7ECF3; color: #0A182C; }
</style>
