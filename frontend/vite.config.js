import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    // 防止压缩器把媒体查询转成 @media (width<=768px) 范围语法
    // （iOS Safari 16.4 以下不支持 → 整段样式被忽略，移动端适配失效）
    cssTarget: ['safari13', 'chrome80'],
  },
  server: {
    proxy: {
      '/api': 'http://localhost:5001',
    },
  },
})
