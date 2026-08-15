import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        // SSE 长连接支持：设置超时为 5 分钟（LLM 生成可能较慢）
        timeout: 300000,
        proxyTimeout: 300000,
      }
    }
  }
})
