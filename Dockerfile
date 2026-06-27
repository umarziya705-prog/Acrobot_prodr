# Dockerfile for AcroBot 2.2
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    portaudio19-dev \
    libportaudio2 \
    libportaudiocpp0 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY config.py .
COPY main.py .
COPY .env.example .

# Create non-root user for security
RUN useradd -m -u 1000 acrobot && \
    chown -R acrobot:acrobot /app
USER acrobot

# Create directories for logs and temp files
RUN mkdir -p /app/logs /app/temp

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV ENVIRONMENT=production
ENV LOG_LEVEL=INFO

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from main import health_check; import sys; sys.exit(0 if health_check()['status'] != 'unhealthy' else 1)" || exit 1

# Run the application
CMD ["python", "main.py"]
