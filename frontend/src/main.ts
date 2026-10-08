import '@quasar/extras/material-icons/material-icons.css'
import 'quasar/src/css/index.sass'
import './theme.css'

import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import {
  Dark, Dialog, Notify, Quasar,
  QAvatar, QBadge, QBanner, QBtn, QCard, QCardActions, QCardSection,
  QDialog, QDrawer, QFile, QFooter, QForm, QHeader, QIcon, QImg,
  QInput, QItem, QItemLabel, QItemSection, QLayout, QLinearProgress,
  QList, QMarkupTable, QMenu, QPage, QPageContainer, QSelect,
  QSeparator, QSkeleton, QSpace, QSpinner, QToolbar,
} from 'quasar'
import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import { initializeTheme } from './theme'

const app = createApp(App)
app.use(Quasar, {
  components: {
    QAvatar, QBadge, QBanner, QBtn, QCard, QCardActions, QCardSection,
    QDialog, QDrawer, QFile, QFooter, QForm, QHeader, QIcon, QImg,
    QInput, QItem, QItemLabel, QItemSection, QLayout, QLinearProgress,
    QList, QMarkupTable, QMenu, QPage, QPageContainer, QSelect,
    QSeparator, QSkeleton, QSpace, QSpinner, QToolbar,
  },
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
  plugins: { Dark, Dialog, Notify },
})
app.use(createPinia())
app.use(VueQueryPlugin, { queryClient: new QueryClient() })
initializeTheme()
app.mount('#app')
