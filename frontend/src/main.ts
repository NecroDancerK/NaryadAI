import '@quasar/extras/material-icons/material-icons.css'
import 'quasar/src/css/index.sass'

import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { Notify, Quasar } from 'quasar'
import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'

const app = createApp(App)
app.use(Quasar, { plugins: { Notify } })
app.use(createPinia())
app.use(VueQueryPlugin, { queryClient: new QueryClient() })
app.mount('#app')
