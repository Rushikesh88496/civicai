# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# CivicAgent frontend — multi-stage production image.
#   deps   : installs dependencies from the lockfile (npm ci).
#   builder: runs `next build` (the app's real production build).
#   runner : slim image that serves the built .next output with `next start`.
# ---------------------------------------------------------------------------

# ---- Stage 1: deps --------------------------------------------------------
FROM node:22-alpine AS deps

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts

# ---- Stage 2: builder ------------------------------------------------------
FROM node:22-alpine AS builder

WORKDIR /app

# NEXT_PUBLIC_* values are inlined into the browser bundle at BUILD time, so
# they are injected here as a build arg (defaults to the Docker-compose URL).
# Set it to the public origin of the backend when deploying behind a domain.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY . .

RUN npm run build

# ---- Stage 3: runner --------------------------------------------------------
FROM node:22-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

# Non-root runtime user.
RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

COPY --from=deps --chown=nextjs:nodejs /app/node_modules ./node_modules
COPY --from=builder --chown=nextjs:nodejs /app/.next ./.next
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/package.json ./package.json
COPY --from=builder --chown=nextjs:nodejs /app/next.config.ts ./next.config.ts

USER nextjs

EXPOSE 3000

# $PORT is the container port Render provisions (unknown at build time); the
# 3000 fallback keeps docker-compose and other local handlers unchanged.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=5 \
    CMD node -e "const p=process.env.PORT||3000; fetch('http://127.0.0.1:'+p+'/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["sh", "-c", "node node_modules/next/dist/bin/next start -H 0.0.0.0 -p \"${PORT:-3000}\""]