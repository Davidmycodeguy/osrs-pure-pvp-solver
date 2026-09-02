import tailwindcss from '@tailwindcss/postcss';
import vinext from 'vinext';
import { defineConfig } from 'vite';

// Local-only build: vinext runs the Next.js-style app on Vite and Node. No hosting plugins.
export default defineConfig({
  css: { postcss: { plugins: [tailwindcss()] } },
  server: {
    // The dataset files under public/data are large and rewritten by the export script;
    // watching them wedges the dev server.
    watch: { ignored: ['**/public/data/**'] },
  },
  plugins: [vinext()],
});
