"""يولّد شعار البرنامج وأيقونته (assets/logo.png و assets/icon.ico)."""
import os

from PIL import Image, ImageDraw, ImageFilter

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
os.makedirs(OUT, exist_ok=True)

S = 512
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

# خلفية مربعة دائرية الحواف بتدرج سماوي
grad = Image.new("RGBA", (S, S))
gd = ImageDraw.Draw(grad)
top, bottom = (41, 170, 255), (10, 84, 168)
for y in range(S):
    k = y / (S - 1)
    gd.line([(0, y), (S, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * k) for i in range(3)) + (255,))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([16, 16, S - 16, S - 16], radius=110, fill=255)
img.paste(grad, (0, 0), mask)

d = ImageDraw.Draw(img)
# سحابة
white = (255, 255, 255, 255)
for cx, cy, r in ((190, 300, 78), (270, 250, 100), (350, 300, 74)):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=white)
d.rounded_rectangle([118, 290, 420, 372], radius=40, fill=white)
# سيف مائل فوق السحابة
blue = (13, 98, 190, 255)
d.polygon([(262, 118), (290, 118), (292, 300), (260, 300)], fill=blue)          # النصل
d.polygon([(262, 118), (276, 84), (290, 118)], fill=blue)                       # الرأس
d.rounded_rectangle([222, 296, 330, 314], radius=8, fill=blue)                   # الواقي
d.rounded_rectangle([266, 312, 286, 360], radius=6, fill=blue)                   # المقبض
d.ellipse([264, 356, 288, 380], fill=blue)

# ظل خفيف
shadow = img.split()[3].filter(ImageFilter.GaussianBlur(10))
final = Image.new("RGBA", (S, S), (0, 0, 0, 0))
final.paste((0, 0, 0, 90), (0, 8), shadow)
final.alpha_composite(img)

final.resize((256, 256), Image.LANCZOS).save(os.path.join(OUT, "logo.png"))
final.save(os.path.join(OUT, "icon.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("assets written to", OUT)
