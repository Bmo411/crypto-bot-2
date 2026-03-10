# Use official minimal Python image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV API_HOST=0.0.0.0
ENV API_PORT=8080

# Create application directory and data directory
WORKDIR /app
RUN mkdir -p /app/data

# Install system dependencies (build-essential needed for some packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . /app/

# Expose the API dashboard port
EXPOSE 8080

# Define a mount point for the database and logs
VOLUME ["/app/data"]

# Run the trading bot
CMD ["python", "run.py"]
