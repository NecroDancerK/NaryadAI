import '@quasar/extras/material-icons/material-icons.css'
import 'quasar/src/css/index.sass'

import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { Notify, Quasar } from 'quasar'
import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'

const app = createApp(App)
app.use(Quasar, {
  config: {
    brand: {
      primary: '#176b47',
      secondary: '#2d7d5a',
      positive: '#278a55',
      negative: '#c4433a',
      warning: '#c98419',
      dark: '#10251e',
    },
  },
  plugins: { Notify },
})
app.use(createPinia())
app.use(VueQueryPlugin, { queryClient: new QueryClient() })
app.mount('#app')
