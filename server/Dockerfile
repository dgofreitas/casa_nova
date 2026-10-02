FROM node:24-alpine

ENV NODE_ENV=production \
    PORT=3000 \
    CASA_NOVA_DADOS=/dados \
    CASA_NOVA_SITE_HTML=/app/site/casa-nova.html

WORKDIR /app/server
COPY server/package.json ./
COPY server/src ./src
COPY server/public ./public
COPY site/casa-nova.html /app/site/casa-nova.html

# mesmo usuário (uid 1000) do crawler: os dois escrevem no volume de dados
RUN mkdir -p /dados && chown node /dados
USER node

EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -qO- http://127.0.0.1:3000/saude || exit 1
CMD ["node", "src/server.js"]
