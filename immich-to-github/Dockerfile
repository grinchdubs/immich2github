# Immich to GitHub Sync Tool - Docker Image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY setup.py .
COPY README.md .

# Bake in the sync config (no secrets — those come from env vars at runtime)
COPY config.yaml ./config.yaml

# Install the package
RUN pip install -e .

# Create directory for state file (mount a volume here to persist it)
RUN mkdir -p /data

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Default command: run the polling daemon against the baked-in config
CMD ["python", "-m", "src.cli", "daemon", "--config", "/app/config.yaml"]
