"""표준 라이브러리만 쓰는 초소형 로드 제너레이터.

N 개의 세션을 돌려가며 agent 의 /chat 을 초당 RPS 회 호출한다.
같은 컨테이너 이미지를 command 만 바꿔 재사용한다.
"""

import json
import os
import random
import time
import urllib.request

TARGET = os.getenv("TARGET_URL", "http://localhost:8000")
RPS = float(os.getenv("RPS", "4"))
SESSIONS = int(os.getenv("SESSIONS", "20"))


def main() -> None:
    session_ids = [f"session-{i:03d}" for i in range(SESSIONS)]
    interval = 1.0 / RPS
    sent = errors = 0
    print(f"loadgen -> {TARGET} rps={RPS} sessions={SESSIONS}", flush=True)
    while True:
        body = json.dumps(
            {
                "session_id": random.choice(session_ids),
                "message": f"question #{sent} about the weekly report",
            }
        ).encode()
        req = urllib.request.Request(
            f"{TARGET}/chat",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp.read()
            sent += 1
        except Exception as exc:  # noqa: BLE001 - demo loop keeps going
            errors += 1
            print(f"error: {exc}", flush=True)
            time.sleep(1)
        if sent and sent % 100 == 0:
            print(f"sent={sent} errors={errors}", flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    main()
