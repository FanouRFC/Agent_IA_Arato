import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('token'))
  const isAuthenticated = computed(() => !!token.value)

  function setToken(value: string) {
    token.value = value
    localStorage.setItem('token', value)
  }
  function logout() {
    token.value = null
    localStorage.removeItem('token')
  }
  return { token, isAuthenticated, setToken, logout }
})
