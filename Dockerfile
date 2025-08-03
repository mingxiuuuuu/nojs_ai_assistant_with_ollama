FROM python:3.11-slim

WORKDIR /app

# Create necessary directories
RUN mkdir -p /app/data /app/logs /app/app/templates

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY main.py .
COPY config.py .
COPY app/ ./app/
COPY services/ ./services/
COPY middleware/ ./middleware/
COPY utils/ ./utils/

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]