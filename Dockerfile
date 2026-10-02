FROM node:22-bookworm-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM node:22-bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv python3-pip ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.lock.txt ./backend/requirements.lock.txt
RUN python3 -m venv /opt/mimas-venv \
    && /opt/mimas-venv/bin/pip install --no-cache-dir -r backend/requirements.lock.txt psycopg2-binary==2.9.11
COPY backend/ ./backend/
COPY ai_core/ ./ai_core/
COPY --from=frontend-build /app/frontend/.next/standalone ./frontend/
COPY --from=frontend-build /app/frontend/.next/static ./frontend/.next/static/
COPY --from=frontend-build /app/frontend/public ./frontend/public/
COPY scripts/start-cloud.sh ./scripts/start-cloud.sh
RUN useradd --create-home --uid 10001 mimas \
    && mkdir -p /app/data \
    && chown mimas:mimas /app/data
USER mimas
ENV DATA_DIR=/app/data PYTHONDONTWRITEBYTECODE=1 PATH="/opt/mimas-venv/bin:$PATH"
EXPOSE 10000
CMD ["bash", "scripts/start-cloud.sh"]