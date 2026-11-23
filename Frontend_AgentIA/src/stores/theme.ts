import { ref, watch } from 'vue'
import { defineStore } from 'pinia'

/** Thème clair / sombre : mémorisé dans le navigateur (si indisponible, le thème du système est suivi). */
export const useThemeStore = defineStore('theme', () => {
  let saved: string | null = null
  try { saved = localStorage.getItem('theme') } catch { /* stockage indisponible */ }
  const systeme = typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: dark)').matches
  const dark = ref(saved ? saved === 'dark' : systeme)
  watch(dark, (v) => document.documentElement.classList.toggle('dark', v), { immediate: true })
  function toggle() {
    dark.value = !dark.value
    try { localStorage.setItem('theme', dark.value ? 'dark' : 'light') } catch { /* stockage indisponible */ }
  }
  return { dark, toggle }
})
