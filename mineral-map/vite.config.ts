import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(() => ({
  plugins: [react()],
  // Deployment base path. The default build works at a domain root; set
  // DEPLOY_BASE_PATH=/minerals/ (leading+trailing slash required) to deploy
  // under a subpath of an existing site. Vite rewrites asset URLs and
  // import.meta.env.BASE_URL accordingly.
  base: process.env.DEPLOY_BASE_PATH || '/',
  // Keep the bundle a single file: the data JSONs dominate transfer size, so
  // code-splitting buys little here and complicates static hosting.
  build: {
    chunkSizeWarningLimit: 1300,
  },
}))
