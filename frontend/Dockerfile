FROM node:22-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm install

ARG VITE_API_URL=/api/v1
ARG VITE_API_TOKEN=
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_API_TOKEN=$VITE_API_TOKEN

COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime

RUN rm -rf /usr/share/nginx/html/*

COPY --from=builder /app/dist /usr/share/nginx/html
COPY docker-entrypoint.sh /docker-entrypoint.sh

RUN printf 'server {\n\
  listen 5173;\n\
  root /usr/share/nginx/html;\n\
  index index.html;\n\
  resolver __RESOLVER__ valid=10s;\n\
  location = /config.js {\n\
    add_header Cache-Control "no-store";\n\
  }\n\
  location /api/v1/alerts/ws {\n\
    set $backend_upstream __UPSTREAM__;\n\
    proxy_pass $backend_upstream;\n\
    proxy_http_version 1.1;\n\
    proxy_set_header Upgrade $http_upgrade;\n\
    proxy_set_header Connection "upgrade";\n\
    proxy_set_header Host $host;\n\
    proxy_read_timeout 3600s;\n\
  }\n\
  location /api/ {\n\
    set $backend_upstream __UPSTREAM__;\n\
    proxy_pass $backend_upstream;\n\
    proxy_set_header Host $host;\n\
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n\
  }\n\
  location / {\n\
    try_files $uri $uri/ /index.html;\n\
  }\n\
}\n' > /etc/nginx/conf.d/default.conf.template

RUN chmod +x /docker-entrypoint.sh

EXPOSE 5173

CMD ["sh", "/docker-entrypoint.sh"]
