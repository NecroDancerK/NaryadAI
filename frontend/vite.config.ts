import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    vue(),
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'НарядAI',
        short_name: 'НарядAI',
        description: 'Выдача и контроль производственных нарядов',
        theme_color: '#12372a',
        background_color: '#f4f7f5',
        display: 'standalone',
        lang: 'ru',
      },
    }),
  ],
})

