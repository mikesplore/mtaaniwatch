import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/health': 'http://localhost:8000',
      '/reports': 'http://localhost:8000',
      '/tasks': 'http://localhost:8000',
      '/crews': 'http://localhost:8000',
      '/clusters': 'http://localhost:8000',
      '/areas': 'http://localhost:8000',
      '/operations': 'http://localhost:8000',
    },
  },
})
