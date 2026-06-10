import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    include: [
      'tests/**/*.test.js',
      'tests/**/*.property.test.js',
    ],
  },
});
