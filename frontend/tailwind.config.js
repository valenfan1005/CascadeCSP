/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        navy: {
          50: '#f0f3ff',
          100: '#dbe1ff',
          200: '#b8c4ff',
          300: '#8a9eff',
          400: '#5b73ff',
          500: '#3651ff',
          600: '#1a2f9e',
          700: '#0f3460',
          800: '#16213e',
          900: '#1a1a2e',
        },
      },
    },
  },
  plugins: [],
}
