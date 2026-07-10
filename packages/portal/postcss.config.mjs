const config = {
  plugins: {
    // Tailwind v4's PostCSS entrypoint. The typography plugin is NOT a PostCSS
    // plugin — it's loaded from CSS via `@plugin "@tailwindcss/typography"` in
    // globals.css. Listing it here makes PostCSS throw "[object Object] is not a
    // PostCSS plugin".
    "@tailwindcss/postcss": {},
  },
};

export default config;
