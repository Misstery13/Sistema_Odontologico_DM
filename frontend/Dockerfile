FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM caddy:2-alpine
COPY Caddyfile Caddyfile.prod Caddyfile.funnel common.caddy /etc/caddy/
COPY --from=build /app/dist /srv
