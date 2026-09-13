FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && addgroup --system app \
    && adduser --system --ingroup app app

COPY service ./service

USER app
EXPOSE 8000

# Behind the Container Apps ingress / APIM boundary, TLS ends before this
# process; trust the proxy's X-Forwarded-* headers so redirects and
# transport-security checks see the real scheme and host.
CMD ["uvicorn", "service.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
