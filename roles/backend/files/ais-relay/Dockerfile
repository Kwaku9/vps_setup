FROM node:22-alpine
WORKDIR /app
COPY package.json ./
RUN npm install --production
COPY ais-relay.js ./
USER node
CMD ["node", "ais-relay.js"]
