# Stage 1: Build React App
FROM node:20-alpine AS builder

WORKDIR /app

# Copy dependency definitions
COPY package*.json ./
RUN npm ci

# Copy application sources
COPY . .

# Pass VITE_API_URL build argument
ARG VITE_API_URL=""
ENV VITE_API_URL=$VITE_API_URL

# Build production assets
RUN npm run build

# Stage 2: Serve with lightweight Nginx runtime
FROM nginx:alpine

# Remove default nginx config and copy custom config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy compiled assets from builder
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
