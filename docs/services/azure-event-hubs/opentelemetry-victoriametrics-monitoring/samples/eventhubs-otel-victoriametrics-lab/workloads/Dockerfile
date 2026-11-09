ARG PYTHON_IMAGE=python@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --requirement requirements.txt

COPY producer.py consumer.py lag.py lag_exporter.py ./

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

USER 10001

CMD ["python", "producer.py"]
