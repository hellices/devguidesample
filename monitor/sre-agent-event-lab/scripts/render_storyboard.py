#!/usr/bin/env python3
import argparse
import json
import re
import textwrap
from pathlib import Path
from typing import Any, Optional, Sequence

from PIL import Image, ImageDraw, ImageFont

from generate_notifications import sanitize


WIDTH = 1280
HEIGHT = 720
BACKGROUND = "#07101F"
PANEL = "#111C2F"
TEXT = "#F8FAFC"
MUTED = "#B8C4D8"
COLORS = {
    "SCENARIO": "#DC2626",
    "EXPECTATION": "#7C3AED",
    "ACTUAL": "#2563EB",
    "OPERATIONAL OUTPUT": "#16A34A",
}
AZURE_RESOURCE_ID_PATTERN = re.compile(
    r"/subscriptions/[^\s,]+", re.IGNORECASE
)
SCENARIOS = {
    "s1": {
        "name": "주문 API HTTP 500",
        "situation": "새 Container App revision의 잘못된 설정으로 주문 요청이 실패한다.",
        "impact": "고객 주문 요청 120건이 HTTP 500으로 실패",
        "expectations": [
            "영향 endpoint와 정확한 UTC onset 식별",
            "Application Insights request와 revision change 상관 분석",
            "안전한 rollback/config restoration 제안",
        ],
        "evidence_keywords": ("120", "FAILURE_MODE", "active revision"),
        "result": "설정 오류를 정확히 찾고 정상 revision 복귀를 확인",
    },
    "s2": {
        "name": "HTTP 200이지만 p95 4초",
        "situation": "응답은 성공하지만 주문 API latency가 사용자 경험을 저하시킨다.",
        "impact": "주문 요청 90건이 약 4초 소요",
        "expectations": [
            "availability와 latency incident 구분",
            "dependency 지연과 application 지연 분리",
            "지연을 만든 revision configuration 식별",
        ],
        "evidence_keywords": ("90", "4.003", "ORDER_DELAY"),
        "result": "ORDER_DELAY_MS=4000을 찾고 정상 latency 복귀를 확인",
    },
    "s3": {
        "name": "Blob RBAC 403/503",
        "situation": "Workload identity의 Blob read role이 삭제되어 문서 API가 실패한다.",
        "impact": "Blob 403과 API 503이 60건 발생",
        "expectations": [
            "Activity Log의 role deletion 식별",
            "Blob dependency 403과 API 503 연결",
            "원래 least-privilege scope의 role 복원 제안",
        ],
        "evidence_keywords": ("causal change", "role", "403"),
        "result": "Role deletion 원인은 찾았지만 recovery endpoint 혼동을 기록",
    },
}


def load_font(size: int, bold: bool = False):
    candidates = [
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    ]
    for candidate in candidates:
        try:
            index = 7 if bold and candidate.endswith(".ttc") else 0
            return ImageFont.truetype(candidate, size, index=index)
        except (OSError, ValueError):
            continue
    return ImageFont.load_default()


def clean_text(value: str) -> str:
    value = public_text(value)
    value = re.sub(r"\[HTTP_TRIGGER_EXECUTION\].*", "", value, flags=re.DOTALL)
    value = value.replace("**", "").replace("`", "")
    return "\n".join(" ".join(line.split()) for line in value.splitlines())


def public_text(value: str) -> str:
    value = sanitize(value)

    def replace_resource_id(match: re.Match) -> str:
        resource_name = match.group(0).rstrip(".)]").split("/")[-1]
        return f"[Azure resource: {resource_name}]"

    return AZURE_RESOURCE_ID_PATTERN.sub(replace_resource_id, value)


def wrap(value: str, width: int = 46, limit: int = 8) -> list[str]:
    lines = []
    for paragraph in clean_text(value).splitlines():
        if not paragraph:
            lines.append("")
            continue
        lines.extend(textwrap.wrap(paragraph, width=width, break_long_words=True))
    if len(lines) > limit:
        lines = lines[:limit]
        lines[-1] = f"{lines[-1][:-3]}..."
    return lines


def find_event(
    timeline: list[dict[str, Any]],
    state: str,
    keywords: tuple[str, ...] = (),
    last: bool = False,
) -> dict[str, Any]:
    matches = [event for event in timeline if event.get("state") == state]
    if keywords:
        preferred = [
            event
            for event in matches
            if any(keyword.lower() in event.get("summary", "").lower() for keyword in keywords)
        ]
        if preferred:
            matches = preferred
    if not matches:
        raise ValueError(f"timeline has no {state} event")
    return matches[-1] if last else matches[0]


def fallback_event(
    alert: dict[str, Any],
    state: str,
    title: str,
    summary: str,
) -> dict[str, Any]:
    return {
        "event_id": state,
        "timestamp": alert["timestamp"],
        "state": state,
        "title": title,
        "summary": summary,
        "source": "capture",
        "source_file": "normalized-timeline.json",
    }


def find_event_or_missing(
    timeline: list[dict[str, Any]],
    state: str,
    missing_state: str,
    alert: dict[str, Any],
    fallback_title: str,
    fallback_summary: str,
    keywords: tuple[str, ...] = (),
    last: bool = False,
) -> dict[str, Any]:
    try:
        return find_event(timeline, state, keywords, last)
    except ValueError:
        try:
            return find_event(timeline, missing_state, last=True)
        except ValueError:
            return fallback_event(
                alert,
                missing_state,
                fallback_title,
                fallback_summary,
            )


def build_frames(
    scenario: str,
    timeline: list[dict[str, Any]],
    ticket_url: str = "",
    email_preview: str = "",
) -> list[dict[str, str]]:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario: {scenario}")
    config = SCENARIOS[scenario]
    alert = find_event(timeline, "alert-fired")
    thread = find_event_or_missing(
        timeline,
        "thread-created",
        "thread-not-created",
        alert,
        "Agent thread가 생성되지 않음",
        "Alert는 발생했지만 matching SRE Agent thread가 생성되지 않음",
    )
    evidence = find_event_or_missing(
        timeline,
        "investigating",
        "investigation-missing",
        alert,
        "조사 evidence가 수집되지 않음",
        "Telemetry · change · code evidence가 수집되지 않음",
        keywords=config["evidence_keywords"],
        last=True,
    )
    conclusion = find_event_or_missing(
        timeline,
        "conclusion",
        "conclusion-missing",
        alert,
        "결론이 수집되지 않음",
        "Capture deadline까지 structured conclusion이 수집되지 않음",
        last=True,
    )
    ticket = ticket_url or "GitHub Issue — 생성 단계에서 URL 연결"
    email = email_preview or "Outlook email draft — 미리보기 연결"

    return [
        {
            "badge": "SCENARIO",
            "title": config["name"],
            "body": f"{config['situation']}\n\n사용자 영향\n{config['impact']}",
            "footer": "설명 frame — 실제 장애 맥락",
        },
        {
            "badge": "EXPECTATION",
            "title": "Agent에게 기대하는 조사",
            "body": "\n".join(f"{index + 1}. {item}" for index, item in enumerate(config["expectations"])),
            "footer": "설명 frame — 성공 기준",
        },
        {
            "badge": "ACTUAL",
            "title": "Azure Monitor가 incident를 감지",
            "body": public_text(
                f"{alert['title']}\n\n{alert['summary']}\nUTC {alert['timestamp']}"
            ),
            "footer": f"실제 evidence — {alert['source_file']}",
        },
        {
            "badge": "ACTUAL",
            "title": "SRE Agent investigation 시작",
            "body": public_text(
                (
                    "Review-mode incident thread created"
                    if thread["state"] == "thread-created"
                    else thread["summary"]
                )
                + f"\n\nUTC {thread['timestamp']}"
            ),
            "footer": f"실제 evidence — {thread['source_file']}",
        },
        {
            "badge": "ACTUAL",
            "title": "Telemetry · Change · Code evidence",
            "body": public_text(evidence["summary"]),
            "footer": f"실제 Agent message — UTC {evidence['timestamp']}",
        },
        {
            "badge": "ACTUAL",
            "title": "Root cause와 조치 방안",
            "body": public_text(conclusion["summary"]),
            "footer": f"실제 Agent conclusion — UTC {conclusion['timestamp']}",
        },
        {
            "badge": "OPERATIONAL OUTPUT",
            "title": "분석을 운영 workflow로 전달",
            "body": (
                f"결과\n{config['result']}\n\n"
                f"Ticket\n{ticket}\n\n"
                f"Email\n{email}\n\n"
                "Review mode — Agent가 임의로 resource를 변경하지 않음"
            ),
            "footer": "Ticket · Email · Teams에 같은 structured summary 재사용",
        },
    ]


def render_frame(frame: dict[str, str], number: int, total: int) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    color = COLORS[frame["badge"]]

    draw.rectangle((0, 0, WIDTH, 90), fill="#0E1930")
    draw.rounded_rectangle((40, 24, 280, 66), radius=20, fill=color)
    draw.text(
        (62, 32),
        frame["badge"],
        font=load_font(21, True),
        fill="#FFFFFF",
    )
    draw.text(
        (1090, 32),
        f"{number} / {total}",
        font=load_font(21, True),
        fill=MUTED,
    )

    draw.rounded_rectangle(
        (54, 130, 1226, 610),
        radius=24,
        fill=PANEL,
        outline="#34445E",
        width=2,
    )
    draw.rectangle((54, 130, 66, 610), fill=color)
    draw.text((92, 164), frame["title"], font=load_font(34, True), fill=TEXT)

    y = 232
    for line in wrap(frame["body"], width=62, limit=11):
        draw.text((94, y), line, font=load_font(22), fill=MUTED)
        y += 33

    draw.rectangle((0, 652, WIDTH, HEIGHT), fill="#0E1930")
    draw.text((54, 674), frame["footer"], font=load_font(18), fill="#94A3B8")
    return image


def render_storyboard(
    scenario: str,
    timeline: list[dict[str, Any]],
    output_dir: Path,
    ticket_url: str = "",
    email_preview: str = "",
) -> dict[str, str]:
    frames_data = build_frames(scenario, timeline, ticket_url, email_preview)
    output_dir.mkdir(parents=True, exist_ok=True)
    frame_paths = []
    images = []
    names = (
        "situation",
        "expectation",
        "alert-fired",
        "thread-created",
        "evidence",
        "conclusion",
        "operational-output",
    )

    for index, (frame, name) in enumerate(zip(frames_data, names), 1):
        image = render_frame(frame, index, len(frames_data))
        path = output_dir / f"{index:02d}-{name}.png"
        image.save(path)
        images.append(image)
        frame_paths.append(str(path))

    durations = [2500, 3000, 1800, 1800, 3000, 3500, 4000]
    gif_path = output_dir / "investigation-guide.gif"
    images[0].save(
        gif_path,
        save_all=True,
        append_images=images[1:],
        duration=durations,
        loop=0,
        disposal=2,
        optimize=False,
    )
    manifest = {
        "scenario": scenario,
        "frames": frames_data,
        "gif": str(gif_path),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    return {"gif": str(gif_path), "frames": frame_paths}


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render SRE incident storyboard")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--timeline", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ticket-url", default="")
    parser.add_argument("--email-preview", default="")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    timeline = json.loads(args.timeline.read_text())
    outputs = render_storyboard(
        scenario=args.scenario,
        timeline=timeline,
        output_dir=args.output_dir,
        ticket_url=args.ticket_url,
        email_preview=args.email_preview,
    )
    print(json.dumps(outputs, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
