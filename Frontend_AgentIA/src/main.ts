import './assets/main.css'
import './assets/premium.css'
import './assets/dark.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import { useThemeStore } from '@/stores/theme'

const app = createApp(App)

app.use(createPinia())
app.use(router)
useThemeStore()   // applique le thème (clair / sombre) avant l'affichage

app.mount('#app')
