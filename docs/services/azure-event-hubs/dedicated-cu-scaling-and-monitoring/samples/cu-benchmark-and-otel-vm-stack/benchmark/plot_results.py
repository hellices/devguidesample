#!/usr/bin/env python3
"""Render the 4 Event Hubs capacity scaling and utilization charts from results/summary.json."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


SAMPLE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY = SAMPLE_ROOT / "results" / "summary.json"
DEFAULT_CHARTS_DIR = SAMPLE_ROOT / "results" / "charts"


def configure_fonts() -> None:
    system = platform.system()
    if system == "Darwin":
        plt.rcParams["font.family"] = ["AppleGothic", "Arial Unicode MS", "sans-serif"]
    else:
        plt.rcParams["font.family"] = ["NanumGothic", "Malgun Gothic", "DejaVu Sans", "sans-serif"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.dpi"] = 160


def plot_01_unit_scaling_curve(summary: dict, out_dir: Path) -> Path:
    rows = summary["unit_scaling"]
    std_by_u = {r["units"]: r for r in rows if r["tier"] == "Standard"}
    prm_by_u = {r["units"]: r for r in rows if r["tier"] == "Premium"}
    ded_rows = sorted([r for r in rows if r["tier"] == "Dedicated"], key=lambda x: x["units"])
    ded_by_u = {r["units"]: r for r in ded_rows}

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15.0, 5.8))
    fig.patch.set_facecolor("#FFFFFF")

    unit_keys = [1, 2, 4, 8]
    units_labels = ["1 Unit\n(1 TU/PU/CU)", "2 Units\n(2 TU/PU/CU)", "4 Units\n(4 TU/PU/CU)", "8 Units\n(8 CU Dedicated)"]
    x = np.arange(len(unit_keys))
    width = 0.25

    std_mbps = [std_by_u[u]["ingress_mbps"] if u in std_by_u else 0.0 for u in unit_keys]
    prm_mbps = [prm_by_u[u]["ingress_mbps"] if u in prm_by_u else 0.0 for u in unit_keys]
    ded_mbps = [ded_by_u[u]["ingress_mbps"] if u in ded_by_u else 0.0 for u in unit_keys]

    bars_std = ax1.bar(
        x - width,
        std_mbps,
        width,
        label="Standard TU (1·2·4 TU 하드 스로틀링 상한 실측)",
        color="#D95F02",
        edgecolor="#8C3B00",
        linewidth=1.0,
    )
    bars_prm = ax1.bar(
        x,
        prm_mbps,
        width,
        label="Premium PU (1·2·4 PU WAN 경유 32p 실측)",
        color="#1B7837",
        edgecolor="#0E441F",
        linewidth=1.0,
    )
    bars_ded = ax1.bar(
        x + width,
        ded_mbps,
        width,
        label="Dedicated CU (1·2·4·8 CU In-Region 64p 실측)",
        color="#0B5394",
        edgecolor="#073763",
        linewidth=1.1,
    )

    for i, b in enumerate(bars_std):
        h = b.get_height()
        if h <= 0:
            continue
        ax1.annotate(
            f"{h:.1f}",
            xy=(b.get_x() + b.get_width() / 2, h),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            fontsize=7.8,
            fontweight="bold",
            color="#7F2704",
        )
    for i, b in enumerate(bars_prm):
        h = b.get_height()
        if h <= 0:
            continue
        ax1.annotate(
            f"{h:.1f}",
            xy=(b.get_x() + b.get_width() / 2, h),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            fontsize=7.8,
            fontweight="bold",
            color="#0E441F",
        )
    for i, b in enumerate(bars_ded):
        h = b.get_height()
        if h <= 0:
            continue
        ax1.annotate(
            f"{h:.1f} MB/s",
            xy=(b.get_x() + b.get_width() / 2, h),
            xytext=(0, 5),
            textcoords="offset points",
            ha="center",
            fontsize=8.3,
            fontweight="bold",
            color="#073763",
        )

    ax1.set_title("용량 단위(1 -> 2 -> 4 -> 8) 증가 시 Standard TU · Premium PU · Dedicated CU 실측 처리량", fontsize=10.6, fontweight="bold", pad=12)
    ax1.set_xticks(x)
    ax1.set_xticklabels(units_labels, fontsize=9.0)
    ax1.set_ylabel("달성 Ingress 처리량 (MB/s)", fontsize=10)
    ax1.set_ylim(0, max(max(ded_mbps, default=100), max(prm_mbps, default=20)) * 1.24)
    ax1.grid(axis="y", linestyle=":", alpha=0.6)
    ax1.legend(loc="upper left", fontsize=8.1, frameon=True)

    # Right panel: Dedicated Cluster CPU (Gateway / Backend %) & p95 latency vs 70% threshold
    x_ded = np.arange(len(ded_rows))
    gw_cpu = [r.get("cluster_gateway_cpu_pct", r.get("cluster_cpu_pct", 0.0)) for r in ded_rows]
    be_cpu = [r.get("cluster_backend_cpu_pct", r.get("cluster_cpu_pct", 0.0)) for r in ded_rows]
    ded_p95 = [r["p95_latency_ms"] for r in ded_rows]

    b_gw = ax2.bar(
        x_ded - width / 2,
        gw_cpu,
        width,
        label="Dedicated Gateway CPU Max (%)",
        color="#E06666",
        edgecolor="#990000",
    )
    b_be = ax2.bar(
        x_ded + width / 2,
        be_cpu,
        width,
        label="Dedicated Backend CPU Max (%)",
        color="#F6B26B",
        edgecolor="#B45F06",
    )
    ax2.axhline(
        70.0,
        linestyle="--",
        color="#990000",
        linewidth=1.6,
        label="Microsoft 권장 스케일 아웃 임계치 (CPU 70%)",
    )
    for b in b_gw:
        h = b.get_height()
        ax2.annotate(
            f"{h:.1f}%",
            xy=(b.get_x() + b.get_width() / 2, h),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            fontsize=7.8,
            fontweight="bold",
            color="#990000",
        )
    for b in b_be:
        h = b.get_height()
        ax2.annotate(
            f"{h:.1f}%",
            xy=(b.get_x() + b.get_width() / 2, h),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            fontsize=7.8,
            fontweight="bold",
            color="#783F04",
        )

    ax2_lat = ax2.twinx()
    ax2_lat.plot(
        x_ded,
        ded_p95,
        marker="s",
        linewidth=2.3,
        color="#0B5394",
        label="Dedicated 64p Send p95 지연 (ms)",
    )
    for i, v in enumerate(ded_p95):
        ax2_lat.annotate(
            f"{v:.1f} ms",
            xy=(x_ded[i], v),
            xytext=(0, 9 if i == len(ded_p95) - 1 else -15),
            textcoords="offset points",
            ha="center",
            fontsize=8.0,
            fontweight="bold",
            color="#0B5394",
            bbox=dict(boxstyle="round,pad=0.15", fc="#FFFFFF", ec="none", alpha=0.82),
        )

    ax2.set_title("Dedicated Cluster 증설(1 -> 2 -> 4 -> 8 CU, 64p) 시 브로커 CPU 포화도 및 p95 지연", fontsize=10.6, fontweight="bold", pad=12)
    ax2.set_xticks(x_ded)
    ax2.set_xticklabels([f"{r['units']} CU" for r in ded_rows], fontsize=9.8)
    ax2.set_ylabel("Azure Monitor Cluster CPU Maximum (%)", fontsize=10, color="#990000")
    ax2_lat.set_ylabel("배치 전송 p95 Latency (ms)", fontsize=10, color="#0B5394")
    ax2.set_ylim(0, 128)
    ax2_lat.set_ylim(0, max(ded_p95 + [60.0]) * 1.38)
    ax2.grid(axis="y", linestyle=":", alpha=0.6)

    lines1, labels1 = ax2.get_legend_handles_labels()
    lines2, labels2 = ax2_lat.get_legend_handles_labels()
    ax2.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=7.6, frameon=True)

    fig.suptitle(
        "실험 1: Standard TU · Premium PU · Dedicated CU(1 -> 2 -> 4 -> 8 CU) 용량 스케일링 및 브로커 CPU 실측",
        fontsize=12.4,
        fontweight="bold",
        y=0.99,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    out_path = out_dir / "01_unit_scaling_curve.png"
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def plot_02_partition_bottleneck(summary: dict, out_dir: Path) -> Path:
    rows = [r for r in summary["partition_bottleneck"] if r.get("tier") == "Dedicated"] or summary["partition_bottleneck"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15.4, 6.0))
    fig.patch.set_facecolor("#FFFFFF")

    p_counts = sorted({r["partitions"] for r in rows})
    x_idx = np.arange(len(p_counts))
    p_labels = [f"{p}p\n(telemetry-p{p})" for p in p_counts]

    cu_list = sorted({r["units"] for r in rows})
    cu_palette = {1: "#D95F02", 2: "#0B5394", 4: "#1B9E77", 8: "#6A3D9A"}
    cu_markers = {1: "o", 2: "s", 4: "^", 8: "D"}

    max_by_cu = {
        cu: max((r["ingress_mbps"] for r in rows if r["units"] == cu), default=0.0)
        for cu in cu_list
    }
    cu_labels = {
        1: f"1 CU 실측 (64~256p 최대 {max_by_cu.get(1, 0.0):.1f} MB/s 포화 수렴)",
        2: f"2 CU 실측 (64~256p 최대 {max_by_cu.get(2, 0.0):.1f} MB/s 포화 수렴)",
        4: f"4 CU 실측 (128~256p 최대 {max_by_cu.get(4, 0.0):.1f} MB/s 포화 수렴)",
        8: f"8 CU 실측 (256p 최대 {max_by_cu.get(8, 0.0):,.1f} MB/s · 1.00 GB/s 도달)",
    }

    # Left panel: X-axis = Partition count (4 -> 16 -> 32 -> 64 -> 128 -> 256), 4 lines = 1, 2, 4, 8 CU
    for cu in cu_list:
        sub = sorted([r for r in rows if r["units"] == cu], key=lambda x: x["partitions"])
        ys = [r["ingress_mbps"] for r in sub]
        ax1.plot(
            x_idx[: len(ys)],
            ys,
            marker=cu_markers[cu],
            linewidth=2.5,
            markersize=7.0,
            color=cu_palette[cu],
            label=cu_labels[cu],
        )
        for i, y in enumerate(ys):
            if i == 0:
                if cu == 2:
                    ax1.annotate(
                        "1·2·4·8 CU 동일\n~46 MB/s",
                        xy=(x_idx[i], y),
                        xytext=(16, 12),
                        textcoords="offset points",
                        ha="center",
                        fontsize=7.6,
                        fontweight="bold",
                        color="#333333",
                        bbox=dict(boxstyle="round,pad=0.14", fc="#FFFFFF", ec="none", alpha=0.82),
                    )
            elif i == 1:
                if cu == 2:
                    ax1.annotate(
                        "1·2·4·8 CU 동일\n~180 MB/s",
                        xy=(x_idx[i], y),
                        xytext=(-6, 12),
                        textcoords="offset points",
                        ha="center",
                        fontsize=7.6,
                        fontweight="bold",
                        color="#333333",
                        bbox=dict(boxstyle="round,pad=0.14", fc="#FFFFFF", ec="none", alpha=0.82),
                    )
            elif i == 2:
                if cu == 8:
                    ax1.annotate(
                        "~298~333 MB/s\n(1CU CPU 78.7%)",
                        xy=(x_idx[i], y),
                        xytext=(-30, 14),
                        textcoords="offset points",
                        ha="center",
                        fontsize=7.5,
                        fontweight="bold",
                        color="#222222",
                        bbox=dict(boxstyle="round,pad=0.14", fc="#FFFFFF", ec="none", alpha=0.82),
                    )
            else:
                offset_map = {
                    (1, 3): (0, -16), (1, 4): (0, -16), (1, 5): (-6, -16),
                    (2, 3): (0, 8),   (2, 4): (0, 8),   (2, 5): (-6, 8),
                    (4, 3): (16, -13), (4, 4): (0, -16), (4, 5): (-6, -16),
                    (8, 3): (-4, 9),  (8, 4): (0, 9),   (8, 5): (-12, 9),
                }
                ax1.annotate(
                    f"{y:,.1f}",
                    xy=(x_idx[i], y),
                    xytext=offset_map.get((cu, i), (0, 8)),
                    textcoords="offset points",
                    ha="center",
                    fontsize=7.8,
                    fontweight="bold",
                    color=cu_palette[cu],
                    bbox=dict(boxstyle="round,pad=0.12", fc="#FFFFFF", ec="none", alpha=0.8),
                )

    for cu in (1, 2, 4):
        if cu in max_by_cu:
            ax1.axhline(
                max_by_cu[cu],
                linestyle=":",
                color=cu_palette[cu],
                alpha=0.55,
                linewidth=1.2,
            )

    ax1.set_title("파티션 수(4 -> 16 -> 32 -> 64 -> 128 -> 256) 증가 시 1·2·4·8 CU 포화 수렴 비교", fontsize=10.6, fontweight="bold", pad=12)
    ax1.set_xticks(x_idx)
    ax1.set_xticklabels(p_labels, fontsize=8.8)
    ax1.set_xlabel("토픽 파티션 수 (Partition Count)", fontsize=10)
    ax1.set_ylabel("달성 Ingress 처리량 (MB/s)", fontsize=10)
    ax1.set_xlim(-0.35, len(p_counts) - 0.5)
    ax1.set_ylim(0, max(r["ingress_mbps"] for r in rows) * 1.24)
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.legend(loc="upper left", fontsize=7.5, frameon=True)

    # Right panel: X-axis = Partition count (4 -> 16 -> 32 -> 64 -> 128 -> 256), 4 lines = Cluster CPU Max (%)
    cpu_offsets = {
        (1, 0): (0, 10),
        (1, 1): (-12, 9),
        (1, 2): (-12, 9),
        (1, 3): (-16, 9),
        (1, 4): (0, 9),
        (1, 5): (-8, 9),
        (2, 2): (-18, 6),
        (2, 3): (16, 9),
        (2, 4): (0, -14),
        (2, 5): (-20, -4),
        (4, 2): (18, -5),
        (4, 3): (-18, -11),
        (4, 4): (-18, -9),
        (4, 5): (-20, 6),
        (8, 0): (10, -13),
        (8, 1): (12, -13),
        (8, 2): (12, -13),
        (8, 3): (14, -12),
        (8, 4): (12, -13),
        (8, 5): (0, -15),
    }
    for cu in cu_list:
        sub = sorted([r for r in rows if r["units"] == cu], key=lambda x: x["partitions"])
        cpus = [r.get("cluster_cpu_pct", r.get("namespace_cpu_pct", 0.0)) for r in sub]
        ax2.plot(
            x_idx[: len(cpus)],
            cpus,
            marker=cu_markers[cu],
            linewidth=2.3,
            markersize=6.6,
            color=cu_palette[cu],
            label=f"{cu} CU 클러스터 CPU Max (%)",
        )
        for i, c in enumerate(cpus):
            if (cu, i) not in cpu_offsets:
                continue
            ax2.annotate(
                f"{c:.1f}%",
                xy=(x_idx[i], c),
                xytext=cpu_offsets[(cu, i)],
                textcoords="offset points",
                ha="center",
                fontsize=7.3,
                fontweight="bold",
                color=cu_palette[cu],
                bbox=dict(boxstyle="round,pad=0.12", fc="#FFFFFF", ec="none", alpha=0.82),
            )

    ax2.axhline(
        70.0,
        linestyle="--",
        color="#990000",
        linewidth=1.6,
        label="Microsoft 권장 스케일 아웃 임계치 (CPU 70%)",
    )
    ax2.set_title("파티션 증가에 따른 1 CU · 2 CU · 4 CU · 8 CU 브로커 CPU 포화 도달 시점", fontsize=10.6, fontweight="bold", pad=12)
    ax2.set_xticks(x_idx)
    ax2.set_xticklabels(p_labels, fontsize=8.8)
    ax2.set_xlabel("토픽 파티션 수 (Partition Count)", fontsize=10)
    ax2.set_ylabel("Azure Monitor Cluster CPU Maximum (%)", fontsize=10)
    ax2.set_xlim(-0.35, len(p_counts) - 0.45)
    ax2.set_ylim(0, 118)
    ax2.grid(True, linestyle=":", alpha=0.6)
    ax2.legend(loc="lower right", fontsize=7.6, frameon=True)

    fig.suptitle(
        "실험 2: 토픽 파티션 수(4 -> 256) 증가에 따른 1 CU · 2 CU · 4 CU · 8 CU 처리량 포화 수렴 및 브로커 CPU 한계 비교",
        fontsize=12.0,
        fontweight="bold",
        y=0.99,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    out_path = out_dir / "02_partition_bottleneck.png"
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def plot_03_gzip_vs_plain(summary: dict, out_dir: Path) -> Path:
    rows = summary["compression_batching"]
    labels = [
        "평문 단건 전송\n(none, linger=0ms)",
        "평문 배치 전송\n(none, linger=20ms)",
        "Gzip 배치 압축\n(gzip, linger=20ms)",
    ]
    x = np.arange(len(rows))
    width = 0.34

    logical_mbps = [r["logical_ingress_mbps"] for r in rows]
    wire_mbps = [r["wire_incoming_bytes_mbps"] for r in rows]
    events_sec = [r["events_per_sec"] for r in rows]
    cpu_pct = [r.get("cluster_cpu_pct", r.get("namespace_cpu_pct", 0.0)) for r in rows]
    p95_ms = [r["p95_latency_ms"] for r in rows]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 5.4))
    fig.patch.set_facecolor("#FFFFFF")

    b_log = ax1.bar(
        x - width / 2,
        logical_mbps,
        width,
        label="원본 로그 처리량 (Logical Payload MB/s)",
        color="#2B83BA",
        edgecolor="#144A6B",
    )
    b_wire = ax1.bar(
        x + width / 2,
        wire_mbps,
        width,
        label="브로커 네트워크 유입량 (IncomingBytes MB/s)",
        color="#FDAE61",
        edgecolor="#B86B14",
    )

    for b in b_log:
        h = b.get_height()
        ax1.annotate(
            f"{h:.2f} MB/s",
            xy=(b.get_x() + b.get_width() / 2, h),
            xytext=(-8, 5),
            textcoords="offset points",
            ha="center",
            fontsize=8.3,
            fontweight="bold",
            color="#144A6B",
        )
    for i, b in enumerate(b_wire):
        h = b.get_height()
        ratio = rows[i]["compression_ratio"]
        suffix = f" (-{(1 - 1/ratio)*100:.0f}%)" if ratio > 1.1 else ""
        ax1.annotate(
            f"{h:.2f} MB/s{suffix}",
            xy=(b.get_x() + b.get_width() / 2, h),
            xytext=(14 if ratio > 1.1 else 10, 5),
            textcoords="offset points",
            ha="center",
            fontsize=8.0,
            fontweight="bold",
            color="#8C4D00",
        )

    ax1.set_title("파이프(|) T-Log 원본 처리량 vs 브로커 네트워크 유입 바이트", fontsize=11.5, fontweight="bold", pad=12)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=9)
    ax1.set_ylabel("처리량 (MB/s)", fontsize=10)
    ax1.set_ylim(0, max(logical_mbps) * 1.28)
    ax1.grid(axis="y", linestyle=":", alpha=0.6)
    ax1.legend(loc="upper left", fontsize=8.5, frameon=True)

    # Right panel: Events/sec vs NamespaceCpuUsage (%) & p95 latency
    bars_evt = ax2.bar(
        x,
        events_sec,
        width=0.42,
        label="초당 메시지 처리율 (IncomingMessages/s)",
        color="#66C2A5",
        edgecolor="#236E57",
    )
    for i, b in enumerate(bars_evt):
        h = b.get_height()
        ax2.annotate(
            f"{h:,.0f} msg/s",
            xy=(b.get_x() + b.get_width() / 2, h),
            xytext=(-18 if i == 0 else 0, 5),
            textcoords="offset points",
            ha="center",
            fontsize=8.5,
            fontweight="bold",
            color="#1B5E49",
        )

    ax2_cpu = ax2.twinx()
    ax2_cpu.plot(
        x,
        cpu_pct,
        marker="o",
        linewidth=2.3,
        color="#D53E4F",
        label="브로커 컴퓨팅 부하 (NamespaceCpuUsage %)",
    )
    ax2_cpu.plot(
        x,
        p95_ms,
        marker="s",
        linestyle="--",
        linewidth=2.0,
        color="#5E4FA2",
        label="Producer p95 Latency (ms)",
    )
    for i, c in enumerate(cpu_pct):
        ax2_cpu.annotate(
            f"CPU {c:.1f}%",
            xy=(x[i], c),
            xytext=(24 if i == 0 else 0, 12),
            textcoords="offset points",
            ha="center",
            fontsize=8.5,
            fontweight="bold",
            color="#9E0142",
            bbox=dict(boxstyle="round,pad=0.18", fc="#FFFFFF", ec="none", alpha=0.82),
        )

    ax2.set_title("배치·Gzip 압축 적용 시 메시지 처리율과 브로커 CPU 사용률 변화", fontsize=11.5, fontweight="bold", pad=12)
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, fontsize=9)
    ax2.set_ylabel("초당 처리 이벤트 수 (Events/s)", fontsize=10, color="#1B5E49")
    ax2_cpu.set_ylabel("CPU 사용률 (%) / p95 지연 (ms)", fontsize=10, color="#9E0142")
    ax2.set_ylim(0, max(events_sec) * 1.32)
    ax2_cpu.set_ylim(0, max(max(cpu_pct), max(p95_ms)) * 1.32)
    ax2.grid(axis="y", linestyle=":", alpha=0.6)

    l1, lb1 = ax2.get_legend_handles_labels()
    l2, lb2 = ax2_cpu.get_legend_handles_labels()
    ax2.legend(l1 + l2, lb1 + lb2, loc="upper left", fontsize=8.2, frameon=True)

    fig.suptitle(
        "실험 3: Filebeat/Kafka 파이프(|) T-Log 전송 시 평문 단건 vs 배치 vs Gzip 압축 실측 비교",
        fontsize=13,
        fontweight="bold",
        y=0.99,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    out_path = out_dir / "03_gzip_vs_plain_throughput.png"
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def plot_04_effective_utilization(summary: dict, out_dir: Path) -> Path:
    series = summary["effective_utilization_timeseries"]
    t_labels = [pt["time_offset"] for pt in series]
    x = np.arange(len(t_labels))

    compute_pct = [pt["compute_saturation_pct"] for pt in series]
    bw_pct = [pt["allocated_bandwidth_utilization_pct"] for pt in series]
    part_pct = [pt["partition_ceiling_utilization_pct"] for pt in series]
    single_q = [pt["otel_single_vm_queue_pct"] for pt in series]
    split_q = [pt["otel_split_gateway_queue_pct"] for pt in series]
    dropped = [pt["otel_single_vm_dropped_points_per_min"] for pt in series]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.8, 5.4))
    fig.patch.set_facecolor("#FFFFFF")

    ax1.plot(
        x,
        compute_pct,
        marker="o",
        linewidth=2.3,
        color="#D73027",
        label="① 컴퓨팅 포화도 % (CPU / Memory Max)",
    )
    ax1.plot(
        x,
        bw_pct,
        marker="s",
        linewidth=2.2,
        color="#4575B4",
        label="② 할당 CU/PU 대역폭 대비 사용률 %",
    )
    ax1.plot(
        x,
        part_pct,
        marker="^",
        linewidth=2.3,
        color="#F46D43",
        linestyle="--",
        label="③ 파티션 상한(1.5 MB/s/p) 대비 사용률 %",
    )
    ax1.axhline(
        70.0,
        linestyle=":",
        color="#7F0000",
        linewidth=1.6,
        label="Microsoft 권장 스케일 아웃 임계치 (CPU 70%)",
    )
    ax1.axvspan(5.5, 8.5, color="#FEE090", alpha=0.35, label="파티션 편중 구간 (8개 파티션 집중)")

    ax1.set_title(
        "실측 베이스라인 기반 4단계 실효 용량 사용률(Effective Capacity Utilization %) 평가 모델",
        fontsize=10.8,
        fontweight="bold",
        pad=12,
    )
    ax1.set_xticks(x)
    ax1.set_xticklabels(t_labels, rotation=30, fontsize=8.5)
    ax1.set_xlabel("경과 시간 (분:초)", fontsize=9.5)
    ax1.set_ylabel("사용률 (%)", fontsize=10)
    ax1.set_ylim(0, 134)
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.legend(loc="upper left", fontsize=7.8, frameon=True)

    # Right panel: OTel Collector queue fill % and dropped metric points
    ax2.plot(
        x,
        single_q,
        marker="o",
        linewidth=2.3,
        color="#C51B7D",
        label="기존 단일 OTel VM 큐 점유율 (%)",
    )
    ax2.plot(
        x,
        split_q,
        marker="s",
        linewidth=2.3,
        color="#276419",
        label="분리형 OTel Gateway + VMCluster 큐 점유율 (%)",
    )
    ax2_drop = ax2.twinx()
    bars_drop = ax2_drop.bar(
        x,
        dropped,
        width=0.45,
        color="#E9A3C9",
        alpha=0.55,
        label="단일 OTel VM 큐 포화 Drop 메트릭 (pts/min)",
    )
    for i, d in enumerate(dropped):
        if d > 0:
            ax2_drop.annotate(
                f"-{d}",
                xy=(x[i], d),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                fontsize=7.8,
                fontweight="bold",
                color="#8E0152",
            )

    ax2.set_title("OTel Collector 인메모리 큐 점유율(%) 및 메트릭 Drop 비교", fontsize=11.3, fontweight="bold", pad=12)
    ax2.set_xticks(x)
    ax2.set_xticklabels(t_labels, rotation=30, fontsize=8.5)
    ax2.set_xlabel("경과 시간 (분:초)", fontsize=9.5)
    ax2.set_ylabel("exporter_queue_size / queue_capacity (%)", fontsize=10, color="#276419")
    ax2_drop.set_ylabel("Enqueue Failed / Dropped Points (건/분)", fontsize=10, color="#8E0152")
    ax2.set_ylim(0, 115)
    ax2_drop.set_ylim(0, max(dropped + [500]) * 1.35)
    ax2.grid(True, linestyle=":", alpha=0.6)

    l1, lb1 = ax2.get_legend_handles_labels()
    l2, lb2 = ax2_drop.get_legend_handles_labels()
    ax2.legend(l1 + l2, lb1 + lb2, loc="upper left", fontsize=8.0, frameon=True)

    fig.suptitle(
        "실험 4 (실측 베이스라인 기반 4단계 용량 사용률·OTel 큐 평가 모델): 3대 실효 사용률(%) 및 큐 적체 비교",
        fontsize=12.5,
        fontweight="bold",
        y=0.99,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    out_path = out_dir / "04_effective_capacity_utilization.png"
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_CHARTS_DIR)
    args = parser.parse_args()

    configure_fonts()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    summary = json.loads(args.summary.read_text(encoding="utf-8"))

    paths = [
        plot_01_unit_scaling_curve(summary, args.out_dir),
        plot_02_partition_bottleneck(summary, args.out_dir),
        plot_03_gzip_vs_plain(summary, args.out_dir),
        plot_04_effective_utilization(summary, args.out_dir),
    ]
    for p in paths:
        print(f"[chart] Generated {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
