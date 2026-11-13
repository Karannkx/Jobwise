"""Generate assets/icon.png, icon.ico (Windows) from code. Run: python scripts/make_icons.py"""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets"
OUT.mkdir(exist_ok=True)

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
# rounded blue tile
d.rounded_rectangle((40, 40, S - 40, S - 40), radius=220, fill=(36, 87, 214, 255))
# document sheet
d.rounded_rectangle((250, 170, 774, 854), radius=56, fill=(255, 255, 255, 255))
for i, w in enumerate((330, 270, 300, 200)):
    y = 330 + i * 92
    d.rounded_rectangle((330, y, 330 + w, y + 36), radius=18, fill=(190, 203, 232, 255))
# check badge
d.ellipse((560, 590, 860, 890), fill=(30, 170, 110, 255), outline=(255, 255, 255, 255), width=18)
d.line([(630, 745), (693, 808), (790, 685)], fill=(255, 255, 255, 255), width=40, joint="curve")

img.resize((512, 512), Image.LANCZOS).save(OUT / "icon.png")
img.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icons written to", OUT)
