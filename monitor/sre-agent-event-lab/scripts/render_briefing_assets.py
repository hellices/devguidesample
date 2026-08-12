#!/usr/bin/env python3
import argparse
import json
import textwrap
from pathlib import Path
from typing import Any, Optional, Sequence
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1600
HEIGHT = 900
BACKGROUND = "#F5F8FC"
NAVY = "#0F1F3D"
BLUE = "#2563EB"
LIGHT_BLUE = "#EAF2FF"
TEAL = "#008272"
GREEN = "#107C10"
ORANGE = "#D97706"
RED = "#C50F1F"
TEXT = "#172033"
MUTED = "#52637A"
BORDER = "#CBD7E8"


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


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    width: int,
    font_size: int,
    fill: str = TEXT,
    bold: bool = False,
    line_gap: int = 8,
) -> int:
    font = load_font(font_size, bold)
    max_chars = max(8, int(width / (font_size * 0.62)))
    lines = []
    for paragraph in text.splitlines():
        if not paragraph:
            lines.append("")
        else:
            lines.extend(
                textwrap.wrap(
                    paragraph,
                    width=max_chars,
                    break_long_words=True,
                    break_on_hyphens=False,
                )
            )
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += font_size + line_gap
    return y


def rounded_panel(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    fill: str = "#FFFFFF",
    outline: str = BORDER,
    accent: str = BLUE,
) -> None:
    draw.rounded_rectangle(bounds, radius=26, fill=fill, outline=outline, width=2)
    x1, y1, _, y2 = bounds
    draw.rounded_rectangle(
        (x1, y1, x1 + 14, y2),
        radius=8,
        fill=accent,
    )


def save_process_png(path: Path) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.text((70, 54), "Azure SRE Agent의 인시던트 대응 흐름", font=load_font(42, True), fill=NAVY)
    draw.text(
        (72, 112),
        "경고를 받은 뒤 관련 근거를 수집하고, 사람의 검토를 거쳐 운영 결과를 공유합니다.",
        font=load_font(24),
        fill=MUTED,
    )

    stages = [
        ("1", "경고 수신", "Azure Monitor\nPagerDuty\nServiceNow", RED),
        ("2", "조사 범위 확인", "영향 서비스\n발생 시각\n고객 영향", ORANGE),
        ("3", "근거 수집", "원격 분석\n변경 이력\n소스 코드", BLUE),
        ("4", "가설 검증", "가능한 원인을 세우고\n근거로 확인", TEAL),
        ("5", "조치 방안 제안", "근본 원인\n완화 조치\n현재 상태", BLUE),
        ("6", "검토 및 승인", "검토 모드에서\n사람이 승인", ORANGE),
        ("7", "티켓과 알림", "GitHub Issue\nOutlook\nMicrosoft Teams", GREEN),
    ]
    positions = [
        (70, 230),
        (440, 230),
        (810, 230),
        (1180, 230),
        (250, 560),
        (620, 560),
        (990, 560),
    ]
    box_w, box_h = 300, 220

    for index, ((number, title, body, color), (x, y)) in enumerate(
        zip(stages, positions)
    ):
        rounded_panel(draw, (x, y, x + box_w, y + box_h), accent=color)
        draw.ellipse((x + 28, y + 26, x + 78, y + 76), fill=color)
        draw.text((x + 45, y + 34), number, font=load_font(21, True), fill="#FFFFFF")
        draw.text((x + 96, y + 30), title, font=load_font(26, True), fill=NAVY)
        draw_wrapped(draw, body, (x + 32, y + 104), box_w - 54, 22, MUTED)

    arrow = "→"
    for x in (380, 750, 1120):
        draw.text((x, 320), arrow, font=load_font(34, True), fill="#7690B5")
    draw.text((1450, 450), "↙", font=load_font(45, True), fill="#7690B5")
    for x in (560, 930):
        draw.text((x, 650), arrow, font=load_font(34, True), fill="#7690B5")

    image.save(path)


def process_svg() -> str:
    labels = [
        ("경고 수신", "Azure Monitor · PagerDuty · ServiceNow"),
        ("조사 범위 확인", "영향 서비스 · 발생 시각 · 고객 영향"),
        ("근거 수집", "원격 분석 · 변경 이력 · 소스 코드"),
        ("가설 검증", "가능한 원인을 근거로 확인"),
        ("조치 방안 제안", "근본 원인 · 완화 조치 · 현재 상태"),
        ("검토 및 승인", "검토 모드에서 사람이 승인"),
        ("티켓과 알림", "GitHub Issue · Outlook · Microsoft Teams"),
    ]
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900">',
        f'<rect width="1600" height="900" fill="{BACKGROUND}"/>',
        f'<text x="70" y="92" font-family="Arial, sans-serif" font-size="42" font-weight="700" fill="{NAVY}">Azure SRE Agent의 인시던트 대응 흐름</text>',
    ]
    positions = [
        (70, 230),
        (440, 230),
        (810, 230),
        (1180, 230),
        (250, 560),
        (620, 560),
        (990, 560),
    ]
    colors = (RED, ORANGE, BLUE, TEAL, BLUE, ORANGE, GREEN)
    for index, ((title, body), (x, y), color) in enumerate(
        zip(labels, positions, colors), 1
    ):
        parts.extend(
            [
                f'<rect x="{x}" y="{y}" width="300" height="220" rx="26" fill="#fff" stroke="{BORDER}" stroke-width="2"/>',
                f'<rect x="{x}" y="{y}" width="14" height="220" rx="7" fill="{color}"/>',
                f'<circle cx="{x + 54}" cy="{y + 52}" r="25" fill="{color}"/>',
                f'<text x="{x + 47}" y="{y + 61}" font-family="Arial, sans-serif" font-size="22" font-weight="700" fill="#fff">{index}</text>',
                f'<text x="{x + 96}" y="{y + 60}" font-family="Arial, sans-serif" font-size="27" font-weight="700" fill="{NAVY}">{escape(title)}</text>',
                f'<text x="{x + 32}" y="{y + 126}" font-family="Arial, sans-serif" font-size="21" fill="{MUTED}">{escape(body)}</text>',
            ]
        )
    parts.append("</svg>")
    return "\n".join(parts)


def save_three_panel_png(path: Path) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.text((70, 54), "실제 활용 예시: 주문 API에서 HTTP 500 발생", font=load_font(42, True), fill=NAVY)
    draw.text(
        (72, 112),
        "한 번의 인시던트가 조사 결과와 운영 후속 작업으로 이어지는 과정을 보여 줍니다.",
        font=load_font(24),
        fill=MUTED,
    )
    panels = [
        (
            "1. 상황",
            "주문 API에서 HTTP 500이 발생했습니다.\n\n고객 주문 요청 120건이 실패했습니다.",
            RED,
        ),
        (
            "2. Agent 조사",
            "Application Insights에서 실패한 요청을 확인했습니다.\n\n배포 설정과 소스 코드를 함께 분석했습니다.",
            BLUE,
        ),
        (
            "3. 운영 결과",
            "근본 원인과 복구 상태를 정리했습니다.\n\nGitHub Issue #43과 이메일 초안을 만들었습니다.",
            GREEN,
        ),
    ]
    for index, (title, body, color) in enumerate(panels):
        x = 70 + index * 510
        rounded_panel(draw, (x, 210, x + 460, 730), accent=color)
        draw.text((x + 40, 255), title, font=load_font(32, True), fill=color)
        draw_wrapped(draw, body, (x + 40, 335), 380, 26, MUTED, line_gap=11)
    image.save(path)


def scenario_svg() -> str:
    panels = [
        (
            "상황",
            "주문 API에서 HTTP 500 발생 / 고객 주문 요청 120건 실패",
            RED,
        ),
        (
            "Agent 조사",
            "Application Insights / 배포 설정 / 소스 코드 분석",
            BLUE,
        ),
        (
            "운영 결과",
            "근본 원인 확인 / GitHub Issue #43 / 이메일 초안",
            GREEN,
        ),
    ]
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900">',
        f'<rect width="1600" height="900" fill="{BACKGROUND}"/>',
        f'<text x="70" y="92" font-family="Arial, sans-serif" font-size="42" font-weight="700" fill="{NAVY}">실제 활용 예시: 주문 API에서 HTTP 500 발생</text>',
    ]
    for index, (title, body, color) in enumerate(panels):
        x = 70 + index * 510
        parts.extend(
            [
                f'<rect x="{x}" y="210" width="460" height="520" rx="26" fill="#fff" stroke="{BORDER}" stroke-width="2"/>',
                f'<rect x="{x}" y="210" width="14" height="520" rx="7" fill="{color}"/>',
                f'<text x="{x + 40}" y="285" font-family="Arial, sans-serif" font-size="32" font-weight="700" fill="{color}">{index + 1}. {escape(title)}</text>',
                f'<text x="{x + 40}" y="380" font-family="Arial, sans-serif" font-size="25" fill="{MUTED}">{escape(body)}</text>',
            ]
        )
    parts.append("</svg>")
    return "\n".join(parts)


def save_conclusion_png(path: Path, timeline: list[dict[str, Any]]) -> None:
    alert = next(event for event in timeline if event["state"] == "alert-fired")
    conclusion = next(
        event for event in reversed(timeline) if event["state"] == "conclusion"
    )
    image = Image.new("RGB", (WIDTH, HEIGHT), "#07101F")
    draw = ImageDraw.Draw(image)
    draw.text((70, 52), "Azure SRE Agent가 확인한 결과", font=load_font(42, True), fill="#FFFFFF")
    draw.text(
        (72, 112),
        f"경고 발생 {alert['timestamp'][11:19]} UTC · 결론 {conclusion['timestamp'][11:19]} UTC",
        font=load_font(23),
        fill="#AFC1DD",
    )
    rounded_panel(
        draw,
        (70, 190, 1530, 790),
        fill="#111C2F",
        outline="#34445E",
        accent=GREEN,
    )
    fields = [
        ("영향을 받은 서비스", "ca-sre-event-lab-vnet"),
        ("원격 분석 원본", "appi-sre-event-lab-95933ae5"),
        ("근본 원인", "revision 0000010에 FAILURE_MODE=http500 설정"),
        ("고객 영향", "GET /api/orders 요청 120건 실패"),
        ("완화 조치", "정상 설정을 사용한 revision으로 복귀"),
        ("안전 제어", "검토 모드에서 Agent가 Azure 리소스를 변경하지 않음"),
    ]
    y = 235
    for label, value in fields:
        draw.text((120, y), label, font=load_font(23, True), fill="#7FB3FF")
        draw.text((430, y), value, font=load_font(25), fill="#F8FAFC")
        y += 82
    image.save(path)


def render_assets(
    timeline: list[dict[str, Any]], output_dir: Path
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    process_svg_path = output_dir / "sre-agent-process.svg"
    process_png_path = output_dir / "sre-agent-process.png"
    scenario_svg_path = output_dir / "s1-three-panel.svg"
    scenario_png_path = output_dir / "s1-three-panel.png"
    conclusion_path = output_dir / "s1-agent-conclusion.png"

    process_svg_path.write_text(process_svg())
    scenario_svg_path.write_text(scenario_svg())
    save_process_png(process_png_path)
    save_three_panel_png(scenario_png_path)
    save_conclusion_png(conclusion_path, timeline)

    return {
        "process_svg": str(process_svg_path),
        "process_png": str(process_png_path),
        "scenario_svg": str(scenario_svg_path),
        "scenario_png": str(scenario_png_path),
        "conclusion_png": str(conclusion_path),
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Korean SRE briefing visuals")
    parser.add_argument("--timeline", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    timeline = json.loads(args.timeline.read_text())
    outputs = render_assets(timeline, args.output_dir)
    print(json.dumps(outputs, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
