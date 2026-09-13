FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bench_runner.py .
ENTRYPOINT ["python", "bench_runner.py"]
