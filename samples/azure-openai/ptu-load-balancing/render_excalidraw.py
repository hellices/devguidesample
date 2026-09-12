"""Render an .excalidraw file (rectangles, text, multi-point arrows) to PNG with Pillow.
Lightweight renderer tailored for the ptu_lb workflow diagrams."""
import json
import sys
from PIL import Image, ImageDraw, ImageFont

SCALE = 2  # supersample for crisp output


def load_font(size):
    for name in [
        "C:/Windows/Fonts/malgun.ttf",   # Korean support
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main(src, dst):
    with open(src, encoding="utf-8") as f:
        data = json.load(f)
    elements = [e for e in data["elements"] if not e.get("isDeleted")]

    # bounds
    max_x = max_y = 0
    for e in elements:
        ex = e["x"] + (e.get("width") or 0)
        ey = e["y"] + (e.get("height") or 0)
        if e["type"] == "arrow":
            for px, py in e["points"]:
                ex = max(ex, e["x"] + px)
                ey = max(ey, e["y"] + py)
        max_x = max(max_x, ex)
        max_y = max(max_y, ey)
    W = int((max_x + 40) * SCALE)
    H = int((max_y + 40) * SCALE)

    img = Image.new("RGB", (W, H), "#ffffff")
    d = ImageDraw.Draw(img)

    def sc(v):
        return int(v * SCALE)

    # rectangles first
    for e in elements:
        if e["type"] != "rectangle":
            continue
        x0, y0 = sc(e["x"]), sc(e["y"])
        x1, y1 = sc(e["x"] + e["width"]), sc(e["y"] + e["height"])
        fill = e.get("backgroundColor")
        if fill == "transparent":
            fill = None
        r = 10 * SCALE
        d.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=fill,
                            outline=e.get("strokeColor", "#1e1e1e"),
                            width=int(max(1, e.get("strokeWidth", 2)) * SCALE))

    # arrows
    def draw_arrow(pts, color, width):
        for i in range(len(pts) - 1):
            d.line([pts[i], pts[i + 1]], fill=color, width=width)
        # arrowhead on last segment
        (x0, y0), (x1, y1) = pts[-2], pts[-1]
        import math
        ang = math.atan2(y1 - y0, x1 - x0)
        L = 12 * SCALE
        for da in (math.radians(150), math.radians(-150)):
            hx = x1 + L * math.cos(ang + da)
            hy = y1 + L * math.sin(ang + da)
            d.line([(x1, y1), (hx, hy)], fill=color, width=width)

    for e in elements:
        if e["type"] != "arrow":
            continue
        pts = [(sc(e["x"] + px), sc(e["y"] + py)) for px, py in e["points"]]
        draw_arrow(pts, e.get("strokeColor", "#1e1e1e"),
                   int(max(1, e.get("strokeWidth", 2)) * SCALE))

    # text on top
    for e in elements:
        if e["type"] != "text":
            continue
        font = load_font(int(e.get("fontSize", 18) * SCALE))
        color = e.get("strokeColor", "#1e1e1e")
        lines = e["text"].split("\n")
        lh = int(e.get("fontSize", 18) * SCALE * e.get("lineHeight", 1.2))
        align = e.get("textAlign", "left")
        box_w = sc(e.get("width") or 0)
        for i, line in enumerate(lines):
            tw = d.textlength(line, font=font)
            tx = sc(e["x"])
            if align == "center":
                tx = sc(e["x"]) + (box_w - tw) / 2
            ty = sc(e["y"]) + i * lh
            d.text((tx, ty), line, fill=color, font=font)

    img.save(dst)
    print(f"saved {dst} ({img.width}x{img.height})")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
