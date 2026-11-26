# --- deps: dev tooling (Tailwind CLI) -----------------------------------------------------
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

# --- dev: used by docker compose (source is bind-mounted; CSS is rebuilt on start) ---------
FROM deps AS dev
COPY . .
EXPOSE 4000
CMD ["npm", "run", "dev"]

# --- build: compile the Tailwind stylesheet --------------------------------------------------
FROM deps AS build
COPY . .
RUN npm run build:css

# --- runtime (default target): no node_modules, only what the server needs ---------------------
FROM node:20-alpine AS runtime
ENV NODE_ENV=production
WORKDIR /app
COPY package.json server.js ./
COPY lib ./lib
COPY --from=build /app/public ./public
USER node
EXPOSE 4000
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1:4000/healthz || exit 1
CMD ["node", "server.js"]
