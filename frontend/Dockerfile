FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci || npm install

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
# BACKEND_URL é lido no build para gerar as regras de proxy (rewrites)
ARG BACKEND_URL=http://api:8000
ENV BACKEND_URL=$BACKEND_URL
# Nome da plataforma exibido no painel
ARG NEXT_PUBLIC_BRAND_NAME=OráculoInvest
ENV NEXT_PUBLIC_BRAND_NAME=$NEXT_PUBLIC_BRAND_NAME
# Link de indicação da Binance (vazio = não mostra)
ARG NEXT_PUBLIC_BINANCE_REF_URL=https://www.binance.com/register?ref=65851965
ENV NEXT_PUBLIC_BINANCE_REF_URL=$NEXT_PUBLIC_BINANCE_REF_URL
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN adduser -D -u 10001 app
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
USER app
EXPOSE 3000
CMD ["node", "server.js"]
