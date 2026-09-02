FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create application non-root user
RUN groupadd -g 1000 promouser && \
    useradd -u 1000 -g promouser -m -s /bin/bash promouser

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create cache and sessions folders with appropriate permissions
RUN mkdir -p /app/media_cache /app/sessions && \
    chown -R promouser:promouser /app

# Copy application source code
COPY --chown=promouser:promouser . /app

# Switch to non-root user
USER promouser

# Basic container healthcheck (for web API service)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
