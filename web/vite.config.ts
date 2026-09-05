import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react(), {
    name: 'landing-page',
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        if (req.url === '/' || req.url?.startsWith('/?')) req.url = '/landing/index.html'
        next()
      })
    },
  }],
  server: { proxy: { '/api': 'http://localhost:8000' } },
})

