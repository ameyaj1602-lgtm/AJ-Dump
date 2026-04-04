FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY *.py ./

# Create data directory for persistent DB
RUN mkdir -p /data

# Environment defaults
ENV DB_PATH=/data/news.db
ENV POLL_INTERVAL_SECONDS=300
ENV MIN_PRIORITY_SCORE=40
ENV LOG_LEVEL=INFO

# Expose dashboard port
EXPOSE 8000

# Default: run agent + web dashboard together
COPY start.sh .
RUN chmod +x start.sh
CMD ["./start.sh"]
