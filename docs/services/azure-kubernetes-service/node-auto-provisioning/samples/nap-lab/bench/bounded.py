#!/usr/bin/env python3
"""명령을 제한 시간 안에서 실행합니다. az처럼 자식 프로세스를 띄우는 명령도 함께 끝냅니다.

사용법: bounded.py <초> <명령> [인수...]
  명령은 새 프로세스 그룹에서 실행하고, 제한 시간을 넘기면 그룹 전체에 TERM(10초 뒤 KILL)을 보내 124로 끝납니다.
  명령이 먼저 끝나도 같은 그룹에 남은 자식이 있으면 제한 시간까지 기다리고, 그때도 남아 있으면 같은 방식으로 끝내 124를 반환합니다.
  이 프로세스가 받은 INT·TERM·HUP은 명령의 프로세스 그룹에 전달합니다. 그 밖에는 명령의 종료 코드를 그대로 반환합니다.
  표준 입력이 터미널이면 명령에 넘기지 않습니다(배경 그룹이 터미널을 읽으면 멈추므로 입력을 기다리지 않게 함).
"""
import os
import signal
import subprocess
import sys
import time

if len(sys.argv) < 3 or not sys.argv[1].isascii() or not sys.argv[1].isdigit() or int(sys.argv[1]) < 1:
    sys.exit("사용법: bounded.py <1 이상의 초> <명령> [인수...]")
limit, cmd = int(sys.argv[1]), sys.argv[2:]
stdin = subprocess.DEVNULL if sys.stdin is None or sys.stdin.isatty() else None
proc = None
pending = []


def forward(sig, _frame):
    # 명령을 만들기 전에 받은 신호는 보관했다가 생성 직후 전달합니다.
    if proc is None:
        pending.append(sig)
        return
    try:
        os.killpg(proc.pid, sig)
    except ProcessLookupError:
        pass


for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    signal.signal(s, forward)

try:
    proc = subprocess.Popen(cmd, stdin=stdin, preexec_fn=os.setpgrp)
except OSError as e:
    print(f"bounded.py: {cmd[0]}: {e.strerror}", file=sys.stderr)
    sys.exit(127)
for s in pending:
    forward(s, None)


def code(rc):
    return 128 - rc if rc < 0 else rc


def group_alive():
    try:
        os.killpg(proc.pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def stop_group():
    """그룹 전체에 TERM을 보내고 10초 안에 사라지지 않으면 KILL합니다."""
    forward(signal.SIGTERM, None)
    # 그룹 리더가 먼저 끝나도 같은 그룹의 자식이 남을 수 있으므로 그룹 전체를 확인합니다.
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        # 리더가 이미 끝났으면 wait가 바로 돌아오므로, 그때는 잠시 쉬며 남은 그룹을 확인합니다.
        step = min(0.2, max(0.0, deadline - time.monotonic()))
        if proc.poll() is None:
            try:
                proc.wait(timeout=step)
            except subprocess.TimeoutExpired:
                pass
        else:
            time.sleep(step)
        if not group_alive():
            break
    else:
        forward(signal.SIGKILL, None)
        proc.wait()


end = time.monotonic() + limit
try:
    rc = proc.wait(timeout=limit)
except subprocess.TimeoutExpired:
    rc = None
# 리더가 끝나도 같은 그룹에 남은 자식은 제한 시간까지 기다립니다. 그 안에 모두 끝나면 리더의 종료 코드를 반환합니다.
while rc is not None and group_alive() and time.monotonic() < end:
    time.sleep(min(0.2, max(0.0, end - time.monotonic())))
if rc is not None and not group_alive():
    sys.exit(code(rc))
print(f"bounded.py: {limit}초 안에 끝나지 않아 중단합니다: {' '.join(cmd)}", file=sys.stderr)
stop_group()
sys.exit(124)
