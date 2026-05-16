FROM python:3.12-slim

# WeasyPrint runtime deps (used from Module 6 onwards; harmless to include now).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libcairo2 \
    libffi-dev \
    libgdk-pixbuf-2.0-0 \
    libssl-dev \
    libpq-dev \
    curl \
  && rm -rf /var/lib/apt/lists/*

# Install uv.
ADD https://astral.sh/uv/install.sh /tmp/install-uv.sh
RUN sh /tmp/install-uv.sh && mv /root/.local/bin/uv /usr/local/bin/uv && rm /tmp/install-uv.sh

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

ENV DJANGO_SETTINGS_MODULE=config.settings.dev
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

COPY deployment/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["runserver"]
