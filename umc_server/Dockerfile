# Use Node.js 18 LTS
FROM node:18-slim

# Set working directory
WORKDIR /app

# Copy server directory for dependencies
COPY server/ ./server/

# Install dependencies
RUN cd server && npm install --production

# Copy the API server file
