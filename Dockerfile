FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CERT_DATA_DIR=/app/data
WORKDIR /app
COPY pyproject.toml requirements.lock ./
COPY app ./app
RUN pip install --no-cache-dir -c requirements.lock . \
    && useradd --create-home --uid 10001 certificate \
    && mkdir -p /app/data \
    && chown certificate:certificate /app/data
USER certificate
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

