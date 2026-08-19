FROM node:24-alpine AS build

WORKDIR /app

COPY package.json ./
RUN npm install --no-audit --no-fund

COPY index.html ./
COPY src ./src
RUN npm run build

FROM nginx:1.30.4-alpine

COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/dist /usr/share/nginx/html

USER 101:101

EXPOSE 8080

ENTRYPOINT []
CMD ["nginx", "-g", "daemon off;"]
