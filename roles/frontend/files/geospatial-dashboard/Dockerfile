FROM node:22-alpine AS base
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .

# --- Development target: Vite HMR ---
FROM base AS dev
EXPOSE 5173
CMD ["npx", "vite", "--host"]

# --- Production build ---
FROM base AS build
RUN npx vite build

# --- Production target: nginx static ---
FROM nginx:alpine AS prod
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
