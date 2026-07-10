FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Optional per-build overrides of the committed defaults in .env.production,
# named after the repo-wide PLATFORM_* convention (the same vars other
# packages read from the deployment's env file) rather than the
# portal-specific NEXT_PUBLIC_* names, so this Dockerfile's build-arg
# interface matches every other package. .env.local
# (Next.js's usual override file) can't be used for this: it's in
# .dockerignore, so it never reaches this build context.
#
# NEXT_PUBLIC_* is only exported when the matching PLATFORM_* arg is
# non-empty — left alone otherwise (never declared as its own ARG), so
# .env.production's file value still applies (Next.js only reads a .env file
# value when the same-named var isn't already present in the process
# environment, and an empty string still counts as present).
ARG PLATFORM_API_URL=""
ARG PLATFORM_SITE_NAME=""
ARG PLATFORM_SITE_TAGLINE=""
RUN [ -n "$PLATFORM_API_URL" ] && export NEXT_PUBLIC_API_URL="$PLATFORM_API_URL"; \
    [ -n "$PLATFORM_SITE_NAME" ] && export NEXT_PUBLIC_SITE_NAME="$PLATFORM_SITE_NAME"; \
    [ -n "$PLATFORM_SITE_TAGLINE" ] && export NEXT_PUBLIC_SITE_TAGLINE="$PLATFORM_SITE_TAGLINE"; \
    npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
