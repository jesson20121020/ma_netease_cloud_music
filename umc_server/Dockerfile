# Use Node.js 20 LTS to support cross-env >=10.1.0
FROM node:20-slim

# Set working directory
WORKDIR /app

# Copy package files first for better caching
COPY server/package*.json ./server/

# Copy server directory for dependencies
COPY server/ ./server/

# Install dependencies
RUN cd server && npm install --production

# Copy the API server file
COPY api-server.js ./api-server.js

# Expose port
EXPOSE 3000

# Start the server
CMD ["node", "api-server.js"]
