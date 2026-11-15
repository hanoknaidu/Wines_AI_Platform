# syntax=docker/dockerfile:1

# =============================================================================
# Wines AI frontend. Two stages: Node builds the Vite bundle; nginx serves the
# static files and forwards /api to the backend (the client always calls a
# relative /api, so no CORS and no base URL is baked into the bundle).
# =============================================================================
FROM node:22-alpine AS build

WORKDIR /app

# Manifest + lockfile first: this layer survives any edit under src/.
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

COPY . .
# Uses .env.production (VITE_USE_MOCKS=false). VITE_* values are fixed at build time.
RUN npm run build


# =============================================================================
# Unprivileged nginx: runs as uid 101 and listens on 8080, matching the
# backend image's non-root stance.
FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime

# Where /api is forwarded. Overridable at `docker run -e BACKEND_ORIGIN=...`.
ENV BACKEND_ORIGIN=http://backend:8010

# The nginx image runs envsubst on /etc/nginx/templates/*.template at startup.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080
