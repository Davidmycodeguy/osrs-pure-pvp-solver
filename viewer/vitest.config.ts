import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

// The lib and component modules import through the "@/" alias that tsconfig defines; vitest needs
// the same mapping. Only the pure modules under lib/ are tested, so no DOM environment is set up.
export default defineConfig({
  resolve: {
    alias: { '@': fileURLToPath(new URL('.', import.meta.url)) },
  },
  test: {
    include: ['lib/**/*.test.ts'],
  },
});
