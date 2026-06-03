# Dockerfile for D-Drive
# Multi-stage build to reduce final image size

# Stage 1: Build stage
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --user --no-cache-dir -r requirements.txt

# Stage 2: Runtime stage
FROM python:3.11-slim as runtime

WORKDIR /app

# Copy Python dependencies from builder
COPY --from=builder /root/.local /root/.local
COPY --from=builder /app/requirements.txt .

# Ensure scripts in .local are usable
ENV PATH=/root/.local/bin:$PATH

# Copy application code
COPY . .

# Create a non-root user for security
RUN useradd -m ddrive && chown -R ddrive:ddrive /app
USER ddrive

# Expose Flask port
EXPOSE ${FLASK_PORT:-5000}

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:${FLASK_PORT:-5000}/api/health', timeout=5)" || exit 1

# Default command
CMD ["python", "app.py"]
