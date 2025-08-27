FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for better caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create volume for database
VOLUME ["/app/data"]

# Set environment variables
ENV DATABASE_PATH=/app/data/bot_database.db
ENV PYTHONUNBUFFERED=1

# Expose port (not needed for Telegram bot, but good practice)
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python3 test_bot.py || exit 1

# Run the bot
CMD ["python3", "bot.py"]