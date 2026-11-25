"""Generate MERSAD AI's Windows desktop application icon using Pillow."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


def build_icon(size: int = 256) -> Image.Image:
    """Draw a crisp square icon with a traffic shield, camera target and plate."""
    scale = size / 256.0
    image = Image.new("RGBA", (size, size), (7, 18, 34, 255))
    draw = ImageDraw.Draw(image)

    def p(value: float) -> int:
        return int(round(value * scale))

    # Deep-blue vertical background gradient.
    pixels = image.load()
    top = (7, 22, 42)
    bottom = (14, 59, 86)
    for y in range(size):
        t = y / max(1, size - 1)
        color = tuple(round(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
        for x in range(size):
            pixels[x, y] = (*color, 255)

    # Framed outer tile.
    draw.rounded_rectangle(
        (p(12), p(12), p(244), p(244)),
        radius=p(48),
        fill=(8, 27, 49, 255),
        outline=(32, 194, 197, 255),
        width=max(1, p(5)),
    )

    # Scanner rings.
    for inset, color, width in [
        (0, (31, 197, 199, 210), 5),
        (13, (31, 197, 199, 105), 3),
    ]:
        box = (p(73 + inset), p(34 + inset), p(183 - inset), p(144 - inset))
        draw.arc(box, 205, 335, fill=color, width=max(1, p(width)))
        draw.arc(box, 25, 155, fill=color, width=max(1, p(width)))

    # Shield mark.
    shield = [
        (p(128), p(42)),
        (p(186), p(63)),
        (p(179), p(129)),
        (p(154), p(171)),
        (p(128), p(188)),
        (p(102), p(171)),
        (p(77), p(129)),
        (p(70), p(63)),
    ]
    draw.polygon(shield, fill=(14, 54, 79, 255), outline=(75, 225, 213, 255))
    draw.line(shield + [shield[0]], fill=(75, 225, 213, 255), width=max(1, p(5)), joint="curve")

    # Road running through the shield.
    road = [(p(108), p(70)), (p(120), p(145)), (p(128), p(159)), (p(136), p(145)), (p(148), p(70))]
    draw.line(road, fill=(225, 245, 247, 255), width=max(2, p(10)), joint="curve")
    for y in (85, 111, 137):
        draw.rounded_rectangle(
            (p(124), p(y), p(132), p(y + 12)),
            radius=p(4),
            fill=(22, 128, 151, 255),
        )

    # License plate / recognition card.
    draw.rounded_rectangle(
        (p(49), p(176), p(207), p(220)),
        radius=p(11),
        fill=(236, 247, 247, 255),
        outline=(58, 218, 205, 255),
        width=max(1, p(3)),
    )
    draw.rounded_rectangle((p(60), p(187), p(196), p(209)), radius=p(5), fill=(14, 45, 68, 255))
    # Stylized "M" formed from clean geometry so no external font is needed.
    draw.line(
        [(p(101), p(202)), (p(108), p(193)), (p(116), p(202)), (p(124), p(193)), (p(131), p(202))],
        fill=(73, 222, 210, 255),
        width=max(2, p(4)),
        joint="curve",
    )
    for x in (79, 175):
        draw.ellipse((p(x - 3), p(195), p(x + 3), p(201)), fill=(73, 222, 210, 255))

    return image


def main() -> int:
    target = Path(__file__).resolve().parent / "MERSAD_Desktop.ico"
    image = build_icon()
    image.save(
        target,
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
    )
    if not target.is_file() or target.stat().st_size < 1024:
        raise RuntimeError("The generated MERSAD desktop icon is missing or unexpectedly small")
    print(f"PASS: generated {target.name} ({target.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
