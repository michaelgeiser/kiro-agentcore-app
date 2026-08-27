FROM public.ecr.aws/docker/library/python:3.12-slim

# Build version: 2026-06-17-v2
WORKDIR /app

# WeasyPrint system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-dejavu-core \
    fonts-liberation \
    fonts-freefont-ttf \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY src/ ./src/

# Set PYTHONPATH so modules resolve correctly
ENV PYTHONPATH="/app/src"

# Startup verification: WeasyPrint can render minimal HTML to PDF
HEALTHCHECK --interval=30s --timeout=10s --retries=1 \
    CMD python -c "from weasyprint import HTML; HTML(string='<p>ok</p>').write_pdf()" || exit 1

CMD ["python", "-m", "deployment.local_runner"]
