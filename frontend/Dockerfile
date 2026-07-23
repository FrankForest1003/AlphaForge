FROM node:22-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

ENV ALPHAFORGE_API_PROXY_TARGET=http://backend:8000

EXPOSE 8501

HEALTHCHECK --interval=20s --timeout=5s --start-period=15s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8501/ >/dev/null || exit 1

CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0", "--port", "8501"]
