"""Draw an original README GIF with explicitly simulated activity (never live app data)."""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
BG, PANEL, BORDER = "#0b1117", "#101922", "#273744"
TEXT, MUTED, BLUE, ORANGE, GREEN = "#d6e4ef", "#839baa", "#91bcdf", "#e9a17b", "#98c8ad"


# ---- font -------------------------------------------------------------------
def font(size, bold=False):
    candidates = [
        Path("C:/Windows/Fonts") / ("consolab.ttf" if bold else "consola.ttf"),
        Path("/usr/share/fonts/truetype/dejavu")
        / ("DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"),
        Path("/System/Library/Fonts/Menlo.ttc"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default(size=size)


# ---- curve ------------------------------------------------------------------
def curve(a, b, bend=0):
    result = []
    for k in range(61):
        t = k / 60
        result.append(
            (a[0] + (b[0] - a[0]) * t + math.sin(t * math.pi) * bend, a[1] + (b[1] - a[1]) * t)
        )
    return result


# ---- frame ------------------------------------------------------------------
def frame(index, count):
    t = index / count
    im = Image.new("RGB", (1120, 650), BG)
    d = ImageDraw.Draw(im)
    d.text((30, 20), "JUSTKERNEL_", font=font(38, True), fill=ORANGE)
    d.text((31, 67), "INDEPENDENT EXPERIMENTS. SHARED PROGRESS.", font=font(13), fill=MUTED)
    d.rounded_rectangle((874, 25, 1090, 58), radius=15, outline=BORDER, fill=PANEL)
    d.ellipse((889, 37, 897, 45), fill=ORANGE)
    d.text((907, 32), "DEMO / MOCK DATA", font=font(14), fill=ORANGE)
    d.line((30, 96, 1090, 96), fill=BORDER)
    d.rounded_rectangle((30, 116, 438, 516), radius=14, fill=PANEL, outline=BORDER)
    d.rounded_rectangle((454, 116, 1090, 516), radius=14, fill=PANEL, outline=BORDER)
    d.text((50, 133), "01 / OPTIMIZATION LOOP", font=font(16, True), fill=TEXT)
    d.text((476, 133), "02 / A2A COLLABORATION", font=font(16, True), fill=TEXT)
    for x in range(52, 430, 20):
        for y in range(175, 500, 20):
            d.point((x, y), fill="#23313e")
    nodes = [
        (230, 193, "SPEC & RULES"),
        (142, 273, "EXPLORE"),
        (324, 273, "REVIEW"),
        (230, 353, "SIMULATE"),
        (142, 433, "VALIDATE"),
        (324, 433, "SHARE"),
    ]
    edges = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 0)]
    glow = Image.new("RGB", im.size, (0, 0, 0))
    g = ImageDraw.Draw(glow)
    for e, (a, b) in enumerate(edges):
        points = curve(nodes[a][:2], nodes[b][:2], 24 if e == 5 else -16)
        d.line(points, fill="#3d596d", width=2)
        offset = (t * 2 + e / 6) % 1
        for tail in range(9):
            pos = points[int(((offset - tail * 0.012) % 1) * 60)]
            col = (
                int(233 * (1 - tail / 10)),
                int(161 * (1 - tail / 10)),
                int(123 * (1 - tail / 10)),
            )
            g.ellipse((pos[0] - 3, pos[1] - 3, pos[0] + 3, pos[1] + 3), fill=col)
    active = int(t * 12) % 6
    for n, (x, y, label) in enumerate(nodes):
        box = (x - 69, y - 19, x + 69, y + 19)
        d.rounded_rectangle(
            box, radius=9, fill="#192a36", outline=ORANGE if n == active else "#3c586a", width=2
        )
        d.text(
            (x, y), label, anchor="mm", font=font(14, True), fill=ORANGE if n == active else TEXT
        )
        if n == active:
            g.rounded_rectangle(box, radius=9, outline=(140, 80, 40), width=3)
    cx, cy = 772, 329
    for rx, ry in [(140, 87), (246, 140)]:
        d.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), outline="#1f303c", width=1)
    positions = []
    for i in range(8):
        angle = i * math.tau / 8 - math.pi / 2 + 0.035 * math.sin(t * math.tau + i)
        x = cx + (239 if i % 2 else 169) * math.cos(angle)
        y = cy + (131 if i % 2 else 105) * math.sin(angle)
        positions.append((x, y))
        d.line(curve((cx, cy), (x, y), 20), fill="#294352", width=1)
    for j in range(3):
        a = (int(t * 8) + j * 2) % 8
        b = (a + 3) % 8
        points = curve(positions[a], positions[b], -24)
        d.line(points, fill="#46657a", width=1)
        p = points[int((t * 3 + j / 3) % 1 * 60)]
        g.ellipse((p[0] - 4, p[1] - 4, p[0] + 4, p[1] + 4), fill=(180, 215, 240))
    for i, (x, y) in enumerate(positions):
        radius = 20 + (3 if i == 2 else 0)
        color = ORANGE if i == int(t * 8) else BLUE
        d.ellipse(
            (x - radius - 5, y - radius - 5, x + radius + 5, y + radius + 5), outline="#355365"
        )
        d.ellipse(
            (x - radius, y - radius, x + radius, y + radius), fill="#203745", outline=color, width=2
        )
        d.text((x, y), f"{i + 1:02d}", font=font(16, True), fill=color, anchor="mm")
        d.text((x, y + 36), "GPT" if i < 4 else "DEEPSEEK", anchor="mm", font=font(11), fill=MUTED)
    d.rounded_rectangle((cx - 39, cy - 30, cx + 39, cy + 30), radius=16, fill=BG, outline="#517082")
    d.text((cx, cy), "A2A", anchor="mm", font=font(24, True), fill=TEXT)
    d.text(
        (cx, 486), "8 TEAMS   /   OWN CODE + OWN EVIDENCE", anchor="mm", font=font(13), fill=MUTED
    )
    d.text((50, 486), nodes[active][2] + "  /  ITERATING", font=font(12), fill=ORANGE)
    # Geometry-driven curve: no measurements or official performance values.
    d.rounded_rectangle((30, 531, 1090, 626), radius=14, fill=PANEL, outline=BORDER)
    d.text((50, 548), "SEARCH TREND", font=font(15, True), fill=TEXT)
    d.text((50, 573), "ILLUSTRATIVE", font=font(12), fill=MUTED)
    vals = [0.09, 0.15, 0.13, 0.25, 0.30, 0.27, 0.49, 0.46, 0.63, 0.70, 0.68, 0.85, 0.82, 0.92]
    best, raw, peak = [], [], 0
    for i, value in enumerate(vals):
        x = 265 + i * 59
        peak = max(peak, value)
        raw.append((x, 606 - value * 57))
        best.append((x, 606 - peak * 57))
    d.line((260, 606, 1050, 606), fill=BORDER)
    d.line(raw, fill="#3b566b", width=2)
    d.line(best, fill=ORANGE, width=2)
    p = best[int(t * (len(best) - 1))]
    g.ellipse((p[0] - 5, p[1] - 5, p[0] + 5, p[1] + 5), fill=(233, 161, 123))
    from PIL import ImageChops

    im = ImageChops.add(im, glow.filter(ImageFilter.GaussianBlur(9)))
    im = ImageChops.add(im, glow)
    return im


# ---- main -------------------------------------------------------------------
def main():
    destination = ROOT / "docs/images/justkernel-demo.gif"
    destination.parent.mkdir(parents=True, exist_ok=True)
    frames = [frame(i, 96) for i in range(96)]
    palette = frames[0].quantize(colors=96)
    indexed = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
    indexed[0].save(
        destination,
        save_all=True,
        append_images=indexed[1:],
        duration=80,
        loop=0,
        optimize=True,
        disposal=1,
    )
    print(f"Original simulated diagram: {destination.name}, {destination.stat().st_size} bytes")
    qa = ROOT / ".justkernel/diagnostics/readme-demo-contact-sheet.png"
    qa.parent.mkdir(parents=True, exist_ok=True)
    sheet = Image.new("RGB", (1120, 1300), BG)
    for n, i in enumerate([0, 24, 48, 72]):
        sheet.paste(frames[i].resize((560, 650)), (n % 2 * 560, n // 2 * 650))
    sheet.save(qa)


if __name__ == "__main__":
    main()
