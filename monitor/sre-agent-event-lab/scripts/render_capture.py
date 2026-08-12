#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1280
HEIGHT = 720
STATE_COLORS = {
    "alert-fired": "#DC2626",
    "thread-created": "#D97706",
    "investigating": "#2563EB",
    "conclusion": "#16A34A",
    "conclusion-missing": "#6B7280",
    "thread-not-created": "#6B7280",
}
SENSITIVE_PATTERN = re.compile(
    r"(?i)(Bearer\s+[A-Za-z0-9._~+/=-]+|InstrumentationKey\s*=|"
    r"ConnectionString\s*=|access_token|connection_string)"
)


def load_font(size: int, bold: bool = False):
    candidates = (
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
        if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def short_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:10]


def compact_title(value: str) -> str:
    if value.startswith("/subscriptions/"):
        return value.rstrip("/").split("/")[-1]
    return value


def ensure_safe(timeline: list[dict[str, Any]]) -> None:
    serialized = json.dumps(timeline, sort_keys=True)
    if SENSITIVE_PATTERN.search(serialized):
        raise ValueError("sensitive content detected in normalized timeline")


def wrapped_lines(value: str, width: int, limit: int) -> list[str]:
    lines = textwrap.wrap(value or "", width=width, break_long_words=True)
    if len(lines) > limit:
        lines = lines[:limit]
        lines[-1] = f"{lines[-1][:-3]}..."
    return lines


def _card(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    title: str,
    lines: list[str],
    color: str,
) -> None:
    draw.rounded_rectangle(bounds, radius=18, fill="#111827", outline="#374151", width=2)
    left, top, right, _ = bounds
    draw.rectangle((left, top, left + 10, bounds[3]), fill=color)
    draw.text((left + 30, top + 22), title, font=load_font(25, True), fill="#F9FAFB")
    y = top + 72
    for line in lines:
        draw.text((left + 30, y), line, font=load_font(20), fill="#D1D5DB")
        y += 31


def render_frame(
    timeline: list[dict[str, Any]], index: int, scenario: str
) -> Image.Image:
    event = timeline[index]
    first_time = parse_timestamp(timeline[0]["timestamp"])
    current_time = parse_timestamp(event["timestamp"])
    elapsed = max(0, int((current_time - first_time).total_seconds()))
    color = STATE_COLORS.get(event["state"], "#6B7280")
    image = Image.new("RGB", (WIDTH, HEIGHT), "#030712")
    draw = ImageDraw.Draw(image)

    draw.rectangle((0, 0, WIDTH, 92), fill="#0F172A")
    draw.text(
        (42, 25),
        f"Azure SRE Agent Evidence Replay - {scenario.upper()}",
        font=load_font(31, True),
        fill="#F9FAFB",
    )
    draw.text(
        (930, 26),
        f"+{elapsed}s  {event['state']}",
        font=load_font(23, True),
        fill=color,
    )

    alert = timeline[0]
    _card(
        draw,
        (40, 125, 415, 585),
        "Azure Monitor Alert",
        wrapped_lines(compact_title(alert["title"]), 30, 3)
        + [f"UTC {alert['timestamp']}", f"ID {short_hash(alert['event_id'])}"],
        STATE_COLORS["alert-fired"],
    )

    timeline_lines = []
    for position, item in enumerate(timeline):
        marker = ">" if position == index else "-"
        timeline_lines.append(f"{marker} {item['state']}  {item['timestamp'][11:19]}Z")
    _card(
        draw,
        (450, 125, 850, 585),
        "Investigation Timeline",
        timeline_lines[:12],
        color,
    )

    _card(
        draw,
        (885, 125, 1240, 585),
        compact_title(event["title"]),
        wrapped_lines(event["summary"], 28, 9)
        + [f"Source: {event['source']}", f"Event: {short_hash(event['event_id'])}"],
        color,
    )

    draw.rectangle((0, 630, WIDTH, HEIGHT), fill="#0F172A")
    draw.text(
        (42, 655),
        f"UTC {event['timestamp']}   evidence: {event['source_file']}",
        font=load_font(20),
        fill="#9CA3AF",
    )
    return image


def mermaid_text(timeline: list[dict[str, Any]]) -> str:
    lines = [
        "sequenceDiagram",
        "    participant AzureMonitor",
        "    participant SREAgent",
        "    participant Evidence",
    ]
    for event in timeline:
        summary = event["summary"].replace("\n", " ").replace(":", "-")[:100].rstrip()
        if event["source"] == "azure-monitor":
            lines.append(f"    AzureMonitor->>SREAgent: {summary}")
        elif event["source"] == "sre-agent":
            lines.append(f"    SREAgent->>Evidence: {event['state']} - {summary}")
        else:
            lines.append(f"    Evidence-->>Evidence: {event['state']} - {summary}")
    return "\n".join(lines) + "\n"


def markdown_text(timeline: list[dict[str, Any]]) -> str:
    first_time = parse_timestamp(timeline[0]["timestamp"])
    rows = [
        "| UTC | Elapsed | State | Source | Summary |",
        "|---|---:|---|---|---|",
    ]
    for event in timeline:
        elapsed = int((parse_timestamp(event["timestamp"]) - first_time).total_seconds())
        summary = event["summary"].replace("|", "\\|").replace("\n", " ")
        rows.append(
            f"| {event['timestamp']} | {elapsed}s | {event['state']} | "
            f"{event['source']} | {summary} |"
        )
    return "\n".join(rows) + "\n"


def select_frame_events(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(timeline) <= 8:
        return timeline

    fixed = [
        event
        for event in timeline
        if event["state"]
        in {
            "alert-fired",
            "thread-created",
            "thread-not-created",
            "investigation-missing",
            "conclusion-missing",
        }
    ]
    investigating = [
        event for event in timeline if event["state"] == "investigating"
    ]
    conclusions = [event for event in timeline if event["state"] == "conclusion"]

    selected_investigating = []
    if investigating:
        sample_count = min(4, len(investigating))
        indices = {
            round(index * (len(investigating) - 1) / max(1, sample_count - 1))
            for index in range(sample_count)
        }
        selected_investigating = [
            investigating[index] for index in sorted(indices)
        ]

    selected = fixed + selected_investigating
    if conclusions:
        selected.append(conclusions[-1])
    return sorted(selected, key=lambda event: parse_timestamp(event["timestamp"]))[:8]


def render_capture(
    timeline: list[dict[str, Any]], output_dir: Path, scenario: str
) -> dict[str, str]:
    if not timeline:
        raise ValueError("timeline must contain at least one event")
    ensure_safe(timeline)
    output_dir.mkdir(parents=True, exist_ok=True)
    frame_timeline = select_frame_events(timeline)

    frame_paths = []
    frames = []
    for index, event in enumerate(frame_timeline):
        safe_state = re.sub(r"[^a-z0-9-]", "-", event["state"].lower())
        path = output_dir / f"{index + 1:02d}-{safe_state}.png"
        frame = render_frame(frame_timeline, index, scenario)
        frame.save(path)
        frame_paths.append(path)
        frames.append(frame)

    durations = [1500] * len(frames)
    durations[-1] = 3000
    gif_path = output_dir / "investigation.gif"
    frames[0].save(
        gif_path,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        disposal=2,
        optimize=False,
    )
    mermaid_path = output_dir / "timeline.mmd"
    markdown_path = output_dir / "timeline.md"
    mermaid_path.write_text(mermaid_text(timeline))
    markdown_path.write_text(markdown_text(timeline))

    return {
        "gif": str(gif_path),
        "mermaid": str(mermaid_path),
        "markdown": str(markdown_path),
        "frames": [str(path) for path in frame_paths],
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render SRE Agent evidence")
    parser.add_argument("timeline", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--scenario", required=True, choices=("s1", "s2", "s3"))
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    timeline = json.loads(args.timeline.read_text())
    outputs = render_capture(timeline, args.output_dir, args.scenario)
    print(json.dumps(outputs, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
