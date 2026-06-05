# Job Application Agent - Hugging Face Spaces Deployment
# Uses: https://huggingface.co/new-space?docker=python

FROM python:3.11-slim

# Install system dependencies for Playwright (browser automation)
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    ca-certificates \
    fontconfig \
    libfontconfig1 \
    libxcomposite1 \
    libxrandr2 \
    libxdamage1 \
    libxkbcommon0 \
    libgbm1 \
    libasound2 \
    libpangocairo-1.0-0 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxcb1 \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright with Chromium browser (needed for job scraping)
RUN pip install playwright \
    && playwright install chromium --with-deps

WORKDIR /app

# Copy requirements first for Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire application
COPY . .

# Create required directories
RUN mkdir -p logs/sessions profiles

# Create persistent data directory structure (maps to HF Spaces /data volume)
RUN mkdir -p /data/logs/sessions /data/profiles

# Copy initial data to /data BEFORE creating symlinks
RUN mkdir -p /data/logs/sessions /data/profiles && \
    cp profiles/profile.json /data/profiles/profile.json 2>/dev/null; \
    cp -r logs/* /data/logs/ 2>/dev/null || true

# Save defaults to a NON-symlinked location for runtime init
# (When HF Spaces mounts the /data persistent volume, symlink targets are empty)
RUN mkdir -p /app/.default && \
    cp profiles/profile.json /app/.default/profile.json 2>/dev/null; \
    test -f resume.pdf && cp resume.pdf /app/.default/resume.pdf 2>/dev/null || true

# Replace local dirs with symlinks to persistent /data
RUN rm -rf logs profiles && \
    ln -sf /data/logs logs && \
    ln -sf /data/profiles profiles && \
    ln -sfT /data/resume.pdf resume.pdf 2>/dev/null || ln -sf /data/resume.pdf resume.pdf

# Hugging Face Spaces expects the app to listen on port 7860
ENV DASHBOARD_HOST=0.0.0.0
ENV DASHBOARD_PORT=7860
ENV HF_SPACE=true
ENV DATA_DIR=/data

# Document the port (HF Spaces maps port 7860 automatically)
EXPOSE 7860

# Default: run the web dashboard
CMD ["python", "-m", "agent", "dashboard"]