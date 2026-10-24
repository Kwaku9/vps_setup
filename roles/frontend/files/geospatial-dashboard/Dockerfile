FROM node:22-alpine AS base
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .

# --- Development target: Vite dev server with HMR ---
# NOTE: this is a development server. It was, for a long time, also what ran in
# production here — which is how nginx.conf drifted out of sync without anyone
# noticing. Use the `prod` target to serve this for real.
FROM base AS dev
EXPOSE 5173
CMD ["npx", "vite", "--host"]

# --- Production build ---
FROM base AS build
# Vite inlines VITE_* values at BUILD time, so these must be present here, not
# only at run time. Anything not passed as a build arg is simply absent from the
# bundle and the matching layer degrades (see README "Running with no keys").
ARG VITE_GOOGLE_MAPS_API_KEY=""
ARG VITE_CESIUM_ION_TOKEN=""
ARG VITE_FIRMS_MAP_KEY=""
ARG VITE_ACLED_PROXY_URL=""
ARG VITE_VPS_LAT=""
ARG VITE_VPS_LON=""
ENV VITE_GOOGLE_MAPS_API_KEY=$VITE_GOOGLE_MAPS_API_KEY \
    VITE_CESIUM_ION_TOKEN=$VITE_CESIUM_ION_TOKEN \
    VITE_FIRMS_MAP_KEY=$VITE_FIRMS_MAP_KEY \
    VITE_ACLED_PROXY_URL=$VITE_ACLED_PROXY_URL \
    VITE_VPS_LAT=$VITE_VPS_LAT \
    VITE_VPS_LON=$VITE_VPS_LON
RUN npx vite build

# --- Production target: nginx static + API proxies ---
FROM nginx:alpine AS prod
# Configs go in as TEMPLATES so the entrypoint can substitute credentials at
# start time. They must never be baked into the image: an image is copied and
# shared, an env var is not.
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY 00-zones.conf /etc/nginx/templates/00-zones.conf.template
# Restrict substitution to exactly these two names, otherwise envsubst would
# also eat nginx's own $uri, $args and $upstream_cache_status.
ENV NGINX_ENVSUBST_FILTER='^(WIGLE_API_TOKEN|ABUSEIPDB_API_KEY)$' \
    WIGLE_API_TOKEN='' \
    ABUSEIPDB_API_KEY=''
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
