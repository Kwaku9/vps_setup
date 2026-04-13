# Use an official Node.js runtime as a parent image
FROM node:22-alpine

# Set the working directory in the container
WORKDIR /app

# Copy package.json and package-lock.json to the working directory
COPY package*.json ./

# Install dependencies, including devDependencies needed for the build
RUN npm install

# Copy the rest of the application's source code from your host to your image filesystem.
COPY . .

# Compile TypeScript to JavaScript
RUN npm run build

# Prune dev dependencies to reduce image size
RUN npm prune --production

# Set default transport to stdio
ENV MCP_TRANSPORT=stdio

# Expose port 9090 for SSE transport
EXPOSE 9090

# Define the command to run your app
CMD ["node", "./dist/server.js"]
