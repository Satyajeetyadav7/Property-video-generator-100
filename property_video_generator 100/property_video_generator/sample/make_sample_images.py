"""Generate six synthetic 'property photos' (illustrations) so the project runs with no real data.

Usage: python sample/make_sample_images.py
"""
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

W, H = 1600, 1000
OUT = Path(__file__).parent / "images"


def gradient(top, bottom):
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return img


def finish(img, name, seed):
    """Soft blur + film grain + vignette so the pictures look a little photographic."""
    rnd = random.Random(seed)
    img = img.filter(ImageFilter.GaussianBlur(1.2))
    px = img.load()
    for _ in range(W * H // 6):
        x, y = rnd.randrange(W), rnd.randrange(H)
        r, g, b = px[x, y]
        n = rnd.randint(-8, 8)
        px[x, y] = (max(0, min(255, r + n)), max(0, min(255, g + n)), max(0, min(255, b + n)))
    vig = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vig).ellipse((-W * 0.25, -H * 0.3, W * 1.25, H * 1.3), fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(160))
    img = Image.composite(img, Image.new("RGB", (W, H), (20, 20, 25)), vig)
    img.save(OUT / name, quality=92)


def exterior():
    img = gradient((120, 180, 235), (225, 240, 250))
    d = ImageDraw.Draw(img)
    d.ellipse((1250, 90, 1390, 230), fill=(255, 236, 170))
    d.rectangle((0, 760, W, H), fill=(88, 140, 90))
    d.rectangle((0, 840, W, 900), fill=(80, 82, 90))
    d.rectangle((330, 180, 1270, 780), fill=(236, 226, 210))
    d.rectangle((330, 180, 1270, 230), fill=(40, 60, 110))
    for row in range(5):
        for col in range(7):
            x, y = 380 + col * 125, 270 + row * 100
            d.rectangle((x, y, x + 70, y + 60), fill=(150, 200, 235), outline=(255, 255, 255), width=3)
            if row % 2 == 0 and col % 3 == 1:
                d.rectangle((x - 12, y + 60, x + 82, y + 72), fill=(70, 80, 100))
    d.rectangle((740, 640, 860, 780), fill=(60, 45, 40))
    for cx in (200, 1400):
        d.rectangle((cx - 10, 640, cx + 10, 780), fill=(90, 60, 40))
        d.ellipse((cx - 90, 520, cx + 90, 700), fill=(50, 120, 60))
    finish(img, "01_exterior.jpg", 1)


def living_room():
    img = Image.new("RGB", (W, H), (232, 222, 206))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 700, W, H), fill=(160, 120, 80))
    d.rectangle((140, 150, 760, 560), fill=(180, 215, 240), outline=(250, 250, 250), width=14)
    d.line([(450, 150), (450, 560)], fill=(250, 250, 250), width=10)
    d.polygon([(140, 560), (760, 560), (900, 880), (60, 880)], fill=(255, 245, 200))
    d.rounded_rectangle((860, 430, 1500, 720), 50, fill=(70, 100, 140))
    d.rounded_rectangle((830, 520, 910, 740), 30, fill=(60, 90, 130))
    d.rounded_rectangle((1450, 520, 1530, 740), 30, fill=(60, 90, 130))
    d.rounded_rectangle((900, 400, 1460, 520), 40, fill=(84, 116, 158))
    d.ellipse((1000, 770, 1500, 880), fill=(210, 190, 160))
    d.rectangle((960, 190, 1360, 360), fill=(250, 245, 235), outline=(90, 70, 50), width=10)
    d.rectangle((990, 220, 1330, 330), fill=(220, 150, 90))
    d.rectangle((1530, 300, 1545, 700), fill=(60, 60, 60))
    d.polygon([(1470, 300), (1600, 300), (1570, 200), (1500, 200)], fill=(250, 220, 140))
    finish(img, "02_living_room.jpg", 2)


def kitchen():
    img = Image.new("RGB", (W, H), (240, 236, 228))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 760, W, H), fill=(190, 185, 175))
    d.rectangle((100, 80, 1500, 330), fill=(245, 245, 245), outline=(180, 180, 180), width=4)
    for i in range(7):
        d.rectangle((100 + i * 200, 80, 300 + i * 200, 330), outline=(190, 190, 190), width=4)
        d.rectangle((280 + i * 200, 190, 290 + i * 200, 240), fill=(120, 120, 120))
    d.rectangle((100, 440, 1500, 480), fill=(60, 60, 66))
    d.rectangle((100, 480, 1500, 780), fill=(70, 110, 120))
    for i in range(7):
        d.rectangle((100 + i * 200, 480, 300 + i * 200, 780), outline=(50, 85, 95), width=4)
        d.rectangle((120 + i * 200, 520, 280 + i * 200, 540), fill=(200, 200, 200))
    d.polygon([(560, 330), (940, 330), (880, 250), (620, 250)], fill=(190, 190, 195))
    d.rectangle((620, 395, 880, 440), fill=(30, 30, 30))
    for cx in (660, 740, 820):
        d.ellipse((cx - 22, 405, cx + 22, 430), outline=(200, 80, 60), width=4)
    d.rectangle((1150, 370, 1190, 440), fill=(200, 80, 70))
    d.ellipse((1250, 395, 1330, 440), fill=(250, 200, 70))
    finish(img, "03_kitchen.jpg", 3)


def bedroom():
    img = Image.new("RGB", (W, H), (222, 214, 228))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 720, W, H), fill=(150, 125, 105))
    d.rectangle((1050, 120, 1500, 520), fill=(200, 225, 245), outline=(255, 255, 255), width=12)
    d.rectangle((300, 260, 1100, 400), fill=(110, 80, 70))
    d.rounded_rectangle((260, 380, 1140, 800), 40, fill=(245, 245, 250))
    d.rounded_rectangle((260, 560, 1140, 800), 40, fill=(110, 150, 190))
    d.rounded_rectangle((340, 410, 620, 520), 40, fill=(255, 255, 255), outline=(200, 200, 210), width=4)
    d.rounded_rectangle((780, 410, 1060, 520), 40, fill=(255, 255, 255), outline=(200, 200, 210), width=4)
    for x in (100, 1200):
        d.rectangle((x, 560, x + 90, 780), fill=(120, 85, 70))
        d.rectangle((x + 40, 480, x + 50, 560), fill=(60, 60, 60))
        d.polygon([(x + 5, 480), (x + 85, 480), (x + 65, 420), (x + 25, 420)], fill=(250, 220, 150))
    finish(img, "04_bedroom.jpg", 4)


def balcony():
    img = gradient((250, 170, 110), (255, 225, 170))
    d = ImageDraw.Draw(img)
    d.ellipse((650, 330, 950, 630), fill=(255, 240, 200))
    rnd = random.Random(7)
    x = 0
    while x < W:
        w, h = rnd.randint(70, 150), rnd.randint(140, 420)
        d.rectangle((x, 700 - h, x + w, 700), fill=(110, 90, 115))
        x += w + rnd.randint(0, 12)
    d.rectangle((0, 700, W, H), fill=(120, 95, 80))
    d.rectangle((0, 560, W, 580), fill=(40, 40, 46))
    for i in range(0, W, 50):
        d.rectangle((i, 580, i + 10, 760), fill=(40, 40, 46))
    for cx in (200, 1380):
        d.polygon([(cx - 60, 800), (cx + 60, 800), (cx + 40, 920), (cx - 40, 920)], fill=(170, 90, 60))
        d.ellipse((cx - 110, 620, cx + 110, 820), fill=(50, 125, 65))
    d.ellipse((600, 820, 1000, 900), fill=(205, 170, 130))
    finish(img, "05_balcony.jpg", 5)


def pool():
    img = gradient((110, 185, 235), (200, 230, 250))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 420, W, H), fill=(225, 215, 195))
    d.rounded_rectangle((220, 520, 1380, 900), 60, fill=(60, 170, 215), outline=(245, 245, 245), width=14)
    for i in range(1, 6):
        d.line([(240, 520 + i * 64), (1360, 520 + i * 64)], fill=(120, 205, 235), width=3)
    d.rectangle((0, 360, W, 430), fill=(90, 140, 95))
    for cx in (300, 700, 1100, 1450):
        d.rectangle((cx - 8, 260, cx + 8, 400), fill=(100, 70, 50))
        d.ellipse((cx - 110, 200, cx + 110, 300), fill=(50, 140, 70))
    for x in (110, 1450):
        d.rounded_rectangle((x, 640, x + 90, 800), 20, fill=(250, 250, 250), outline=(200, 200, 200), width=3)
    finish(img, "06_clubhouse_pool.jpg", 6)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for fn in (exterior, living_room, kitchen, bedroom, balcony, pool):
        fn()
    print("Wrote 6 images to", OUT)
