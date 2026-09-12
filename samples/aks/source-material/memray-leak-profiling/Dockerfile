# 앱 이미지는 깨끗하게 유지 — gdb/memray 등 프로파일링 도구는
# 별도 디버그 이미지(debug/Dockerfile)에 두고 kubectl debug 로 붙인다.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py loadgen.py ./

EXPOSE 8000

# 단일 프로세스 uvicorn == 컨테이너 PID 1 → memray attach 대상이 명확
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
