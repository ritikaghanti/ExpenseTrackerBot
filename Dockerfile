# Start with an official Python base image (choose a specific version if needed)
FROM python:3.11-slim

# Set environment variables to prevent interactive prompts during package installs
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies:
# - Tesseract OCR engine
# - Supporting libraries (like libtesseract-dev)
# - Clean up apt cache afterwards to keep the image small
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libtesseract-dev \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code into the container
COPY . .

# Expose the port the app runs on (matching your app.run or Gunicorn)
EXPOSE 5001

# Command to run your application using Gunicorn (production server)
# The default port Render expects is often 10000, but Gunicorn defaults to 8000.
# We'll tell Gunicorn to bind to the port Render provides via the $PORT env var, or default to 5001 if testing locally.
CMD gunicorn --bind 0.0.0.0:$PORT --workers 1 app:app
# Note: Render automatically sets the $PORT environment variable.
# For local testing, you might need to adjust or run Flask directly.
# Or adjust the EXPOSE and CMD port if needed. Let's start with this.