# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime
ENV API_UPSTREAM=http://api:8000 NGINX_ENVSUBST_FILTER=API_UPSTREAM
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /web/dist /usr/share/nginx/html
RUN chown -R nginx:nginx /var/cache/nginx /etc/nginx/conf.d /usr/share/nginx/html && touch /var/run/nginx.pid && chown nginx:nginx /var/run/nginx.pid
USER nginx
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD wget -qO- http://127.0.0.1:8080/ >/dev/null || exit 1
