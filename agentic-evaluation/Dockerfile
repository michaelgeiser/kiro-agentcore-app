FROM public.ecr.aws/docker/library/python:3.12-slim

# Build version: 2026-06-17-v2
WORKDIR /app

# Install dependencies first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY src/ ./src/

# Set PYTHONPATH so modules resolve correctly
ENV PYTHONPATH="/app/src"

CMD ["python", "-m", "deployment.local_runner"]
