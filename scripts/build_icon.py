"""Render original SVG/PNG artwork for the integration (requires Pillow)."""

from math import cos, radians, sin
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def cubic(a, b, c, d):
    points = []
    for step in range(65):
        t = step / 64
        points.append(
            tuple(
                (1 - t) ** 3 * a[i]
                + 3 * (1 - t) ** 2 * t * b[i]
                + 3 * (1 - t) * t * t * c[i]
                + t**3 * d[i]
                for i in (0, 1)
            )
        )
    return points


def main():
    brand = ROOT / "custom_components/rostov_vodokanal/brand"
    brand.mkdir(exist_ok=True)
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    svg = """<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
<defs><linearGradient id="water" x2="0" y2="1"><stop stop-color="#20B8CC"/><stop offset="1" stop-color="#0B6FA4"/></linearGradient></defs>
<path d="M128 18 C111 48 44 104 44 160 C44 212 82 240 128 240 C174 240 212 212 212 160 C212 104 145 48 128 18Z" fill="url(#water)"/>
<circle cx="128" cy="160" r="55" fill="#F4FBFF"/>
<path d="M85 144 A46 46 0 0 1 171 144" fill="none" stroke="#0B3157" stroke-width="4" stroke-linecap="round"/>
<path d="M128 166 L158 141" stroke="#E86D5A" stroke-width="6" stroke-linecap="round"/>
<circle cx="128" cy="166" r="6" fill="#0B3157"/>
</svg>"""
    (assets / "icon.svg").write_text(svg + "\n")
    scale = 8
    size = 256 * scale
    mask = Image.new("L", (size, size))
    points = (
        cubic((128, 18), (111, 48), (44, 104), (44, 160))
        + cubic((44, 160), (44, 212), (82, 240), (128, 240))
        + cubic((128, 240), (174, 240), (212, 212), (212, 160))
        + cubic((212, 160), (212, 104), (145, 48), (128, 18))
    )
    ImageDraw.Draw(mask).polygon(
        [(round(x * scale), round(y * scale)) for x, y in points], fill=255
    )
    gradient = Image.new("RGBA", (size, size))
    draw = ImageDraw.Draw(gradient)
    for y in range(size):
        ratio = y / (size - 1)
        color = tuple(
            round(a + ratio * (b - a))
            for a, b in zip((32, 184, 204), (11, 111, 164), strict=True)
        ) + (255,)
        draw.line((0, y, size, y), fill=color)
    gradient.putalpha(mask)
    draw = ImageDraw.Draw(gradient)

    def box(x, y, radius):
        return tuple(
            round(v * scale) for v in (x - radius, y - radius, x + radius, y + radius)
        )

    draw.ellipse(box(128, 160, 55), fill="#F4FBFF")
    draw.arc(box(128, 160, 46), start=200, end=340, fill="#0B3157", width=4 * scale)
    for angle in [200, 235, 270, 305, 340]:
        draw.line(
            [
                (
                    round((128 + r * cos(radians(angle))) * scale),
                    round((160 + r * sin(radians(angle))) * scale),
                )
                for r in (37, 45)
            ],
            fill="#0B3157",
            width=3 * scale,
        )
    draw.line(
        (128 * scale, 166 * scale, 158 * scale, 141 * scale),
        fill="#E86D5A",
        width=6 * scale,
    )
    draw.ellipse(box(128, 166, 6), fill="#0B3157")
    for filename, dimension in [("icon.png", 256), ("icon@2x.png", 512)]:
        gradient.resize((dimension, dimension), Image.Resampling.LANCZOS).save(
            brand / filename, optimize=True
        )


if __name__ == "__main__":
    main()
