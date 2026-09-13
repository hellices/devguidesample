# memray 디버그 전용 이미지 — kubectl debug (ephemeral container) 로 붙여서 사용
# 앱 이미지는 깨끗하게 유지하고, 프로파일링 도구는 전부 여기에 몰아넣는다.
#
# ⚠️ 베이스 이미지는 앱과 동일한 python:3.12-slim 을 사용해야 한다.
#    memray attach 는 "타깃 프로세스 안"에서 import memray 를 실행하므로
#    타깃에 복사해 넣을 memray 확장 모듈이 타깃의 파이썬(3.12) ABI 와 일치해야 함.
FROM python:3.12-slim

# gdb    : memray attach 가 실행 중인 프로세스에 트래커를 주입할 때 사용
# procps : 공유 PID 네임스페이스에서 ps 로 타깃 PID 확인용
RUN apt-get update \
    && apt-get install -y --no-install-recommends gdb procps \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "memray>=1.15"

CMD ["sleep", "infinity"]
