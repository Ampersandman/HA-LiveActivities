"""Render the original code-defined Home Island mark (development-only Pillow)."""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "custom_components" / "home_island" / "brand"


def render() -> None:
    BRAND.mkdir(exist_ok=True)
    # The vector source and raster use the same simple geometric house/island mark.
    (BRAND / "icon.svg").write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
<rect x="16" y="16" width="480" height="480" rx="112" fill="#09131B"/>
<ellipse cx="256" cy="344" rx="152" ry="38" fill="#4DE8CC"/>
<path d="M140 252 L256 144 L372 252 L348 278 L256 192 L164 278Z" fill="#F7FBFF"/>
<path d="M180 258 L256 188 L332 258 L332 334 L180 334Z" fill="#F7FBFF"/>
<rect x="237" y="270" width="38" height="64" rx="10" fill="#09131B"/>
<path d="M154 406 H358" stroke="#4DE8CC" stroke-width="14" stroke-linecap="round"/>
</svg>\n""",
        encoding="utf-8",
    )
    size = 2048
    image = Image.new("RGBA", (size, size))
    draw = ImageDraw.Draw(image)

    def box(values):
        return tuple(value * 4 for value in values)

    def polygon(points):
        return [(x * 4, y * 4) for x, y in points]

    draw.rounded_rectangle(box((16, 16, 496, 496)), radius=448, fill="#09131B")
    draw.ellipse(box((104, 306, 408, 382)), fill="#4DE8CC")
    draw.polygon(
        polygon([(140, 252), (256, 144), (372, 252), (348, 278), (256, 192), (164, 278)]), fill="#F7FBFF"
    )
    draw.polygon(polygon([(180, 258), (256, 188), (332, 258), (332, 334), (180, 334)]), fill="#F7FBFF")
    draw.rounded_rectangle(box((237, 270, 275, 334)), radius=40, fill="#09131B")
    draw.rounded_rectangle(box((147, 399, 365, 413)), radius=28, fill="#4DE8CC")
    image.resize((512, 512), Image.Resampling.LANCZOS).save(BRAND / "icon.png")


if __name__ == "__main__":
    render()
