#!/usr/bin/env python3
"""Рендер моушн‑ролика «Вернисаж. Ереван под открытым небом» по script.md.

Фото берутся из тех же архивов, что и в shotlist.md:
  --google  папка с распакованным vernissage_reviews_shortlist.zip
  --yandex  папка с распакованным vernissage_yandex_shortlist.zip
  --commons папка с фото Commons (vernissage/photos, см. download_photos.py)
  --fonts   папка с Montserrat.ttf и NotoSansArmenian.ttf (Google Fonts)

  python3 render.py --google G --yandex Y --commons C --fonts F -o vernissage.mp4
  python3 render.py ... --preview 3.0,40,118   # только PNG‑кадры на этих секундах
  python3 render.py ... --music track.mp3       # подложить музыку

Без --music ролик собирается с тихой аудиодорожкой: музыку можно добавить
этим же скриптом или в любом монтажном редакторе.
"""
import argparse
import glob
import math
import os
import subprocess
import sys
from functools import lru_cache
from multiprocessing import Pool

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

W, H, FPS = 1920, 1080, 30
CREAM = (245, 237, 224)
TUFF = (217, 150, 122)
POM = (158, 27, 50)
APRICOT = (244, 162, 89)
OBSIDIAN = (28, 28, 30)
WHITE = (255, 255, 255)

A = None  # argparse namespace, set in main / worker init


# ---------------------------------------------------------------- easing
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def lerp(a, b, p):
    return a + (b - a) * p


def ease_out(p):
    return 1 - (1 - clamp(p)) ** 3


def ease_in_out(p):
    p = clamp(p)
    return 3 * p * p - 2 * p * p * p


def ease_back(p):
    p = clamp(p)
    c = 1.70158
    return 1 + (c + 1) * (p - 1) ** 3 + c * (p - 1) ** 2


def bounce(p):
    p = clamp(p)
    n, d = 7.5625, 2.75
    if p < 1 / d:
        return n * p * p
    if p < 2 / d:
        p -= 1.5 / d
        return n * p * p + 0.75
    if p < 2.5 / d:
        p -= 2.25 / d
        return n * p * p + 0.9375
    p -= 2.625 / d
    return n * p * p + 0.984375


# ---------------------------------------------------------------- assets
def find_photo(key):
    kind, n = key[0], key[1:]
    if kind == "R":
        hits = glob.glob(os.path.join(A.google, f"*_{int(n):03d}_*.jpg"))
    elif kind == "Y":
        hits = glob.glob(os.path.join(A.yandex, f"*_Y{int(n):03d}_*.jpg"))
    else:
        hits = [os.path.join(A.commons, n)]
    if not hits or not os.path.exists(hits[0]):
        sys.exit(f"Нет фото для {key}")
    return hits[0]


@lru_cache(maxsize=None)
def font(size, weight="ExtraBold", family="Montserrat"):
    f = ImageFont.truetype(os.path.join(A.fonts, f"{family}.ttf"), size)
    f.set_variation_by_name(weight)
    return f


@lru_cache(maxsize=24)
def cover(key, scale=1.12):
    """Фото, заполняющее кадр 16:9 с запасом под наезд камеры.
    Вертикальные фото кладутся карточкой на размытый фон."""
    im = ImageOps.exif_transpose(Image.open(find_photo(key))).convert("RGB")
    tw, th = int(W * scale), int(H * scale)
    if im.width / im.height < 1.25:
        bg = ImageOps.fit(im, (tw // 4, th // 4)).filter(ImageFilter.GaussianBlur(12)).resize((tw, th))
        bg = Image.blend(bg, Image.new("RGB", bg.size, OBSIDIAN), 0.35)
        fh = int(th * 0.86)
        fg = im.resize((int(im.width * fh / im.height), fh), Image.LANCZOS)
        card = Image.new("RGB", (fg.width + 24, fg.height + 24), WHITE)
        card.paste(fg, (12, 12))
        sh = Image.new("RGBA", (card.width + 80, card.height + 80), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rectangle((40, 50, card.width + 40, card.height + 50), fill=(0, 0, 0, 150))
        sh = sh.filter(ImageFilter.GaussianBlur(18))
        x, y = (tw - card.width) // 2, (th - card.height) // 2
        bg.paste(sh, (x - 40, y - 40), sh)
        bg.paste(card, (x, y))
        return bg
    return ImageOps.fit(im, (tw, th), Image.LANCZOS)


def kenburns(key, p, z0=1.0, z1=1.08, px=(0, 0), py=(0, 0)):
    img = cover(key)
    z = lerp(z0, z1, ease_in_out(p) * 0.6 + p * 0.4)
    cw, ch = img.width / (1.12 * z) * 1.0, img.height / (1.12 * z)
    cx = img.width / 2 + lerp(px[0], px[1], p) * (img.width - cw) / 2
    cy = img.height / 2 + lerp(py[0], py[1], p) * (img.height - ch) / 2
    box = (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
    return img.resize((W, H), Image.BILINEAR, box=box)


@lru_cache(maxsize=None)
def shade(strength=0.55, top=0.0):
    """Затемнение снизу (и при желании сверху) под текст."""
    g = Image.new("L", (1, H))
    for y in range(H):
        b = clamp((y / H - 0.45) / 0.55) ** 1.4 * strength
        t = clamp((0.35 - y / H) / 0.35) ** 1.4 * top
        g.putpixel((0, y), int(255 * max(b, t)))
    layer = Image.new("RGBA", (W, H), OBSIDIAN + (0,))
    layer.putalpha(g.resize((W, H)))
    return layer


def darken(img, k):
    return Image.blend(img, Image.new("RGB", img.size, OBSIDIAN), k)


# ---------------------------------------------------------------- text sprites
@lru_cache(maxsize=None)
def text_sprite(text, size, weight="ExtraBold", color=WHITE, family="Montserrat", shadow=True):
    if family == "Montserrat" and any("\u0530" <= ch <= "\u058f" for ch in text):
        family = "NotoSansArmenian"
        weight = {"Black": "ExtraBold"}.get(weight, weight)
    f = font(size, weight, family)
    # Высота спрайта — по метрикам шрифта, чтобы слова одной строки стояли на одной базовой линии
    ref = font(size, "Bold")
    asc, desc = ref.getmetrics()
    l, _, r, _ = f.getbbox(text, anchor="ls")
    pad = 30
    im = Image.new("RGBA", (r - l + pad * 2, asc + desc + pad * 2), (0, 0, 0, 0))
    base = pad + asc
    if shadow:
        s = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(s).text((pad - l + 3, base + 5), text, font=f, fill=(0, 0, 0, 170), anchor="ls")
        im = Image.alpha_composite(im, s.filter(ImageFilter.GaussianBlur(7)))
    ImageDraw.Draw(im).text((pad - l, base), text, font=f, fill=color + (255,), anchor="ls")
    return im


def with_alpha(sprite, o):
    if o >= 0.999:
        return sprite
    s = sprite.copy()
    s.putalpha(s.getchannel("A").point(lambda a: int(a * o)))
    return s


def paste(frame, sprite, x, y, o=1.0, anchor="lt"):
    if o <= 0.003:
        return
    sw, sh = sprite.size
    if anchor[0] == "m":
        x -= sw // 2
    elif anchor[0] == "r":
        x -= sw
    if anchor[1] == "m":
        y -= sh // 2
    elif anchor[1] == "b":
        y -= sh
    frame.alpha_composite(with_alpha(sprite, o), (int(x), int(y)))


def words(frame, t, t0, t1, text, x, y, size=72, weight="ExtraBold", color=WHITE, anchor="l",
          stagger=0.12, family="Montserrat"):
    """Кинетический текст: слова всплывают по одному, в конце строка гаснет."""
    if not (t0 <= t < t1):
        return
    parts = text.split(" ")
    sprites = [text_sprite(w, size, weight, color, family) for w in parts]
    space = int(size * 0.28) - 60
    total = sum(s.width for s in sprites) + space * (len(sprites) - 1)
    cx = x - total // 2 if anchor == "m" else (x - total if anchor == "r" else x)
    out = clamp((t1 - t) / 0.3)
    for i, s in enumerate(sprites):
        p = ease_out((t - t0 - i * stagger) / 0.4)
        if p > 0:
            paste(frame, s, cx, y - s.height // 2 + (1 - p) * 45, p * out)
        cx += s.width + space


def typewriter(frame, t, t0, t1, text, x, y, size=72, weight="Medium", color=WHITE, cps=22, anchor="lm"):
    if not (t0 <= t < t1):
        return
    n = int((t - t0) * cps)
    shown = text[: max(0, min(len(text), n))]
    if not shown:
        return
    cursor = "|" if n < len(text) + 8 and int(t * 3) % 2 == 0 else ""
    s = text_sprite(shown + cursor, size, weight, color)
    paste(frame, s, x, y, clamp((t1 - t) / 0.3), anchor)


def chip(frame, t, t0, t1, text, x, y, size=46, bg=POM, fg=WHITE, anchor="m"):
    if not (t0 <= t < t1):
        return
    s = chip_sprite(text, size, bg, fg)
    p = ease_back((t - t0) / 0.45)
    sc = lerp(0.6, 1.0, p)
    o = clamp((t - t0) / 0.2) * clamp((t1 - t) / 0.3)
    if sc < 0.999:
        s = s.resize((max(1, int(s.width * sc)), max(1, int(s.height * sc))), Image.BILINEAR)
    paste(frame, s, x, y, o, anchor + "m" if len(anchor) == 1 else anchor)


@lru_cache(maxsize=None)
def chip_sprite(text, size, bg, fg):
    f = font(size, "Bold")
    l, t, r, b = f.getbbox(text)
    px, py = int(size * 0.6), int(size * 0.38)
    w, h = r - l + px * 2, b - t + py * 2
    im = Image.new("RGBA", (w + 40, h + 40), (0, 0, 0, 0))
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((20, 26, w + 20, h + 26), h // 2, fill=(0, 0, 0, 120))
    im = Image.alpha_composite(im, sh.filter(ImageFilter.GaussianBlur(8)))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((20, 20, w + 20, h + 20), h // 2, fill=bg + (255,))
    d.text((20 + px - l, 20 + py - t), text, font=f, fill=fg + (255,))
    return im


@lru_cache(maxsize=None)
def shine_band():
    band = Image.new("L", (900, 1), 0)
    for x in range(900):
        band.putpixel((x, 0), int(150 * math.exp(-((x - 450) / 140) ** 2)))
    band = band.resize((900, H * 2)).rotate(20, expand=True)
    layer = Image.new("RGBA", band.size, (255, 248, 235, 0))
    layer.putalpha(band)
    return layer


def shine(frame, p):
    """Блик, проходящий по кадру (лак на картине, блеск обсидиана)."""
    if 0 < p < 1:
        b = shine_band()
        x = lerp(-b.width, W, ease_in_out(p))
        frame.alpha_composite(b, (int(x), (H - b.height) // 2))


# ---------------------------------------------------------------- scene helpers
def photo(key, z0=1.0, z1=1.08, px=(0, 0), py=(0, 0), dark=0.0, shaded=0.55, top=0.0):
    def draw(t, dur):
        im = kenburns(key, t / dur, z0, z1, px, py)
        if dark:
            im = darken(im, dark)
        im = im.convert("RGBA")
        if shaded or top:
            im.alpha_composite(shade(shaded, top))
        return im
    return draw


@lru_cache(maxsize=None)
def polaroid(key, w=760, angle=0.0, sepia=0.0):
    im = ImageOps.exif_transpose(Image.open(find_photo(key))).convert("RGB")
    im = ImageOps.fit(im, (w, int(w * 0.75)), Image.LANCZOS)
    if sepia:
        g = ImageOps.grayscale(im)
        sep = ImageOps.colorize(g, (60, 40, 25), (250, 235, 205))
        im = Image.blend(im, sep, sepia)
    m = int(w * 0.05)
    card = Image.new("RGBA", (w + 2 * m, im.height + m + int(w * 0.18)), (252, 250, 245, 255))
    card.paste(im, (m, m))
    sh = Image.new("RGBA", (card.width + 100, card.height + 100), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle((50, 62, card.width + 50, card.height + 62), fill=(0, 0, 0, 110))
    sh = sh.filter(ImageFilter.GaussianBlur(20))
    sh.alpha_composite(card, (50, 50))
    return sh.rotate(angle, Image.BICUBIC, expand=True)


def timeline(frame, t, active, prev=None, move=(0, 0.6)):
    """Шкала времени внизу кадра; подсвечивается активная отметка."""
    marks = ["1970‑е", "1980‑е", "1988", "1990‑е", "2016"]
    xs = [150 + i * 205 for i in range(len(marks))]
    y = 990
    d = ImageDraw.Draw(frame)
    d.line((100, y, 1020, y), fill=TUFF + (255,), width=4)
    cur = xs[active] if prev is None else lerp(xs[prev], xs[active], ease_in_out((t - move[0]) / move[1]))
    d.line((100, y, cur, y), fill=POM + (255,), width=8)
    for i, (x, m) in enumerate(zip(xs, marks)):
        on = abs(x - cur) < 5
        r = 16 if on else 9
        d.ellipse((x - r, y - r, x + r, y + r), fill=(POM if on else TUFF) + (255,))
        s = text_sprite(m, 34 if on else 28, "Bold" if on else "Medium", POM if on else (120, 90, 75), shadow=False)
        paste(frame, s, x, y - 40, 1.0, "mb")


def solid(color):
    def draw(t, dur):
        return Image.new("RGBA", (W, H), color + (255,))
    return draw


# ---------------------------------------------------------------- scenes
# Каждый сегмент: (начало, конец, фон(t_local, dur), переход_в_сек)
SEG = []
# Оверлеи: функции f(frame, t_global)
OV = []


def seg(t0, t1, fn, xfade=0.0):
    SEG.append((t0, t1, fn, xfade))


def ov(fn):
    OV.append(fn)
    return fn


# 1 · Интро 0:00–0:05
seg(0.0, 1.8, solid(OBSIDIAN))
for i, k in enumerate(["R041", "R033", "R165", "R460", "R648", "Y329"]):
    seg(1.8 + i * 0.3, 2.1 + i * 0.3, photo(k, 1.05, 1.12, shaded=0.2))
seg(3.6, 5.0, photo("R290", 1.0, 1.06, shaded=0.6), xfade=0.0)


@ov
def intro_title(fr, t):
    word = "ВЕРНИСАЖ"
    if t < 1.8:
        size = 190
        sprites = [text_sprite(ch, size, "Black", CREAM) for ch in word]
        total = sum(s.width - 50 for s in sprites)
        x = W // 2 - total // 2
        for i, s in enumerate(sprites):
            p = bounce((t - 0.15 - i * 0.11) / 0.55)
            if t - 0.15 - i * 0.11 > 0:
                paste(fr, s, x, lerp(-260, H // 2 - s.height // 2, p), 1.0)
            x += s.width - 50
    if 1.7 <= t < 1.9:  # вспышка
        o = 1 - abs(t - 1.8) / 0.1
        fr.alpha_composite(Image.new("RGBA", (W, H), (255, 250, 240, int(255 * clamp(o)))))
    if 3.6 <= t < 5.0:
        s = text_sprite(word, 170, "Black", CREAM)
        p = ease_out((t - 3.6) / 0.5)
        paste(fr, s, W // 2, H // 2 + (1 - p) * 30, p * clamp((5.0 - t) / 0.25), "mm")
        words(fr, t, 4.0, 5.0, "Ереван · Երևան", W // 2, H // 2 + 140, 46, "SemiBold", CREAM, "m")


# 2 · Ереван на карте 0:05–0:12
def map_bg(t, dur):
    fr = Image.new("RGBA", (W, H), OBSIDIAN + (255,))
    d = ImageDraw.Draw(fr)
    z = 1 + 3 * ease_in_out(t / 3.5)
    step = 120 * z
    cx, cy = W / 2, H / 2
    off_x, off_y = cx % step, cy % step
    for i in range(-2, int(W / step) + 3):
        x = off_x + i * step
        d.line((x, 0, x, H), fill=(60, 55, 55, 255), width=1)
    for i in range(-2, int(H / step) + 3):
        y = off_y + i * step
        d.line((0, y, W, y), fill=(60, 55, 55, 255), width=1)
    rings = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rings)
    for k in range(3):
        r = ((t * 260 + k * 180) % 540)
        a = int(200 * (1 - r / 540))
        rd.ellipse((cx - r, cy - r, cx + r, cy + r), outline=APRICOT + (a,), width=3)
    fr.alpha_composite(rings)
    pin = ease_back((t - 0.8) / 0.5)
    if t > 0.8:
        py = lerp(cy - 220, cy - 60, pin)
        d.ellipse((cx - 22, py - 22, cx + 22, py + 22), fill=POM + (255,))
        d.polygon([(cx - 16, py + 12), (cx + 16, py + 12), (cx, py + 60)], fill=POM + (255,))
        d.ellipse((cx - 8, py - 8, cx + 8, py + 8), fill=CREAM + (255,))
    return fr


seg(5.0, 8.6, map_bg)
seg(8.6, 12.0, photo("R026", 1.0, 1.12, shaded=0.65), xfade=0.35)


@ov
def map_text(fr, t):
    words(fr, t, 6.0, 8.6, "ЕРЕВАН", W // 2, H // 2 + 130, 110, "Black", CREAM, "m")
    typewriter(fr, t, 6.6, 8.6, "40.17° N · 44.51° E", W // 2, H // 2 + 230, 40, "Medium", APRICOT, 24, "mm")
    words(fr, t, 9.0, 12.0, "вся Армения —", W // 2, 800, 84, "ExtraBold", WHITE, "m")
    words(fr, t, 9.5, 12.0, "за один час", W // 2, 905, 96, "Black", APRICOT, "m", stagger=0.15)


# 3 · Вход и ряды 0:12–0:20
seg(12.0, 14.4, photo("Y329", 1.04, 1.12, px=(0.3, 0.1), shaded=0.3))
seg(14.4, 16.8, photo("R008", 1.0, 1.08, shaded=0.4), xfade=0.25)
seg(16.8, 20.0, photo("R554", 1.02, 1.1, px=(-0.4, 0.4), shaded=0.5), xfade=0.25)


@ov
def stalls_chips(fr, t):
    chip(fr, t, 17.1, 20.0, "~1000 продавцов", 520, 860, 50)
    chip(fr, t, 17.6, 20.0, "350 м рядов", 960, 940, 50, APRICOT, OBSIDIAN)
    chip(fr, t, 18.1, 20.0, "вход бесплатный", 1400, 860, 50, CREAM, POM)


# 4 · Слово «вернисаж» 0:20–0:32
def varnish(key, z0, z1):
    base = photo(key, z0, z1, shaded=0.7)

    def draw(t, dur):
        fr = base(t, dur)
        shine(fr, (t - 0.4) / 2.2)
        return fr
    return draw


seg(20.0, 24.4, varnish("R175", 1.0, 1.08), xfade=0.3)
seg(24.4, 28.4, varnish("R188", 1.04, 1.1), xfade=0.3)
seg(28.4, 32.0, photo("R028", 1.0, 1.1, shaded=0.7), xfade=0.3)


@ov
def vernissage_word(fr, t):
    typewriter(fr, t, 20.6, 24.4, "vernissage", 150, 820, 120, "SemiBold", CREAM, 9, "lm")
    words(fr, t, 21.9, 24.4, "(фр.)", 150, 935, 48, "Medium", APRICOT)
    words(fr, t, 24.8, 28.4, "показ картин", 150, 810, 92, "Black", WHITE, stagger=0.15)
    words(fr, t, 25.3, 28.4, "до открытия выставки", 150, 915, 64, "SemiBold", APRICOT)
    words(fr, t, 28.8, 32.0, "в Ереване —", 150, 820, 80, "ExtraBold", WHITE)
    words(fr, t, 29.3, 32.0, "с конца 1970‑х", 150, 925, 92, "Black", APRICOT)


# 5 · 1980‑е 0:32–0:45
def era80(t, dur):
    fr = Image.new("RGBA", (W, H), CREAM + (255,))
    pol = polaroid("C" + "Armenia, Yerevan (2166087660).jpg", 740, -4, 0.55)
    p = ease_out(t / 0.8)
    fr.alpha_composite(pol, (int(lerp(W, 1090, p)), int(110 + math.sin(t * 0.8) * 6)))
    timeline(fr, t, 1, 0, (0.2, 1.0))
    s = text_sprite("фото 2006 г.", 26, "Medium", (130, 100, 85), shadow=False)
    paste(fr, s, 1440, 70, clamp((t - 1) / 0.5), "mm")
    return fr


seg(32.0, 45.0, era80, xfade=0.35)


@ov
def era80_text(fr, t):
    words(fr, t, 32.6, 45.0, "1980‑е", 120, 260, 150, "Black", POM)
    words(fr, t, 34.2, 45.0, "художники выставляют", 120, 430, 58, "Bold", OBSIDIAN)
    words(fr, t, 34.7, 45.0, "картины прямо на улице", 120, 505, 58, "Bold", OBSIDIAN)
    words(fr, t, 38.5, 45.0, "не рынок —", 120, 640, 62, "ExtraBold", POM)
    words(fr, t, 39.0, 45.0, "выставка под открытым небом", 120, 720, 56, "Bold", OBSIDIAN)


# 6 · 1988 → 1990‑е 0:45–0:55
def era90(t, dur):
    fr = Image.new("RGBA", (W, H), CREAM + (255,))
    items = [("CErevan - Vernissage 01.JPG", 470, -6, 1000, 60, 0.2),
             ("CErevan - Vernissage 02.JPG", 470, 5, 1380, 210, 1.2),
             ("CYerevan Vernissage view.jpg", 500, -2, 1110, 370, 2.2)]
    for key, w, ang, x, y, at in items:
        if t > at:
            p = ease_back((t - at) / 0.6)
            pol = polaroid(key, w, ang, 0.35)
            fr.alpha_composite(pol, (int(x), int(lerp(H + 50, y, p))))
    timeline(fr, t, 3, 1, (0.4, 1.4))
    s = text_sprite("фото 2005–2007 гг.", 26, "Medium", (130, 100, 85), shadow=False)
    paste(fr, s, 1500, 40, clamp((t - 3) / 0.5), "mm")
    return fr


seg(45.0, 55.0, era90, xfade=0.3)


@ov
def era90_text(fr, t):
    words(fr, t, 45.5, 55.0, "1988 · 1990‑е", 120, 260, 110, "Black", POM)
    words(fr, t, 47.0, 55.0, "приходят резчики,", 120, 420, 58, "Bold", OBSIDIAN)
    words(fr, t, 47.5, 55.0, "ювелиры, ткачи", 120, 495, 58, "Bold", OBSIDIAN)
    words(fr, t, 50.0, 55.0, "рынок, который", 120, 640, 64, "ExtraBold", POM)
    words(fr, t, 50.4, 55.0, "кормит мастеров", 120, 720, 64, "ExtraBold", POM)


# 7 · Сквер Сарьяна → ул. Арама 0:55–1:02
@lru_cache(maxsize=None)
def round_thumb(key, d=340):
    im = ImageOps.fit(ImageOps.exif_transpose(Image.open(find_photo(key))).convert("RGB"), (d, d), Image.LANCZOS)
    m = Image.new("L", (d, d), 0)
    ImageDraw.Draw(m).ellipse((0, 0, d, d), fill=255)
    out = Image.new("RGBA", (d + 16, d + 16), (0, 0, 0, 0))
    ImageDraw.Draw(out).ellipse((0, 0, d + 16, d + 16), fill=WHITE + (255,))
    im = im.convert("RGBA")
    im.putalpha(m)
    out.alpha_composite(im, (8, 8))
    return out


def split_map(t, dur):
    fr = Image.new("RGBA", (W, H), CREAM + (255,))
    d = ImageDraw.Draw(fr)
    p = ease_in_out((t - 0.6) / 1.6)
    ax, bx, y = lerp(W / 2, 470, p), lerp(W / 2, 1450, p), 560
    d.line((ax, y, bx, y), fill=TUFF + (255,), width=6)
    if p > 0.95:
        d.polygon([(bx - 60, y - 22), (bx - 60, y + 22), (bx - 24, y)], fill=POM + (255,))
    for x, key in ((ax, "C2025-05-18 Yerevan, Saryan park.jpg"), (bx, "R026")):
        th = round_thumb(key)
        o = clamp((t - 1.6) / 0.5)
        paste(fr, th, x, y - 40, o, "mb")
        d.ellipse((x - 18, y - 18, x + 18, y + 18), fill=POM + (255,))
    return fr


seg(55.0, 59.6, split_map, xfade=0.3)
seg(59.6, 62.0, photo("C" + "Yerevan Vernissage by ArmAg (1).jpg", 1.0, 1.08, shaded=0.6), xfade=0.3)


@ov
def split_text(fr, t):
    words(fr, t, 56.8, 59.6, "художники —", 470, 660, 44, "Bold", OBSIDIAN, "m")
    words(fr, t, 57.0, 59.6, "в сквере Сарьяна", 470, 715, 44, "ExtraBold", POM, "m")
    words(fr, t, 57.6, 59.6, "рынок —", 1450, 660, 44, "Bold", OBSIDIAN, "m")
    words(fr, t, 57.8, 59.6, "у площади Республики", 1450, 715, 44, "ExtraBold", POM, "m")
    words(fr, t, 60.0, 62.0, "2016 · новые павильоны", W // 2, 900, 76, "Black", WHITE, "m")


# 8 · Что здесь искать 1:02–1:10
def reveal(t, dur):
    fr = Image.new("RGBA", (W, H), POM + (255,))
    img = kenburns("Y371", t / dur, 1.0, 1.1)
    img = darken(img, 0.45).convert("RGBA")
    r = ease_out((t - 0.2) / 1.2) * 1200
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).ellipse((W / 2 - r, H / 2 - r, W / 2 + r, H / 2 + r), fill=255)
    fr.paste(img, (0, 0), m)
    return fr


seg(62.0, 70.0, reveal, xfade=0.0)


@ov
def what_text(fr, t):
    if 63.0 <= t < 70.0:
        s = text_sprite("ЧТО ЗДЕСЬ ИСКАТЬ", 140, "Black", CREAM)
        p = ease_back((t - 63.0) / 0.6)
        sc = lerp(0.7, 1.0, p)
        s2 = s.resize((int(s.width * sc), int(s.height * sc)), Image.BILINEAR)
        paste(fr, s2, W // 2, H // 2, clamp((t - 63) / 0.2) * clamp((70 - t) / 0.3), "mm")
        words(fr, t, 64.0, 70.0, "6 вещей, за которыми сюда едут", W // 2, H // 2 + 130, 44, "SemiBold", APRICOT, "m")


# 9–14 · Каталог 1:10–1:48
CATALOG = [
    (70.0, 76.0, "01", "КОВРЫ", "ручная работа", ["R164", "R836", "Y174"]),
    (76.0, 82.0, "02", "ДУДУК", "абрикосовое дерево", ["Y008", "R033", "Y083"]),
    (82.0, 88.0, "03", "НАРДЫ", "с Араратом на крышке", ["R108", "R734", "Y015"]),
    (88.0, 94.0, "04", "ГРАНАТ", "символ Армении", ["R744", "R392", "Y116"]),
    (94.0, 100.0, "05", "ОБСИДИАН", "вулканическое стекло", ["R867", "R748", "R693"]),
    (100.0, 108.0, "06", "АНТИКВАРИАТ", "машина времени", ["R460", "R824", "R153", "R542"]),
]
for t0, t1, num, name, sub, keys in CATALOG:
    step = (t1 - t0) / len(keys)
    for i, k in enumerate(keys):
        a, b = t0 + i * step, t0 + (i + 1) * step
        if num == "05" and i == 0:
            seg(a, b, varnish(k, 1.0, 1.1), xfade=0.0)
        else:
            seg(a, b, photo(k, 1.0 + 0.04 * (i % 2), 1.1 - 0.04 * (i % 2),
                            px=((-0.5, 0.5) if i % 2 else (0.4, -0.3)), shaded=0.7), xfade=0.2 if i else 0.0)


@ov
def catalog_text(fr, t):
    for t0, t1, num, name, sub, keys in CATALOG:
        if t0 <= t < t1:
            n = text_sprite(num, 150, "Black", APRICOT)
            p = ease_out((t - t0) / 0.5)
            paste(fr, n, lerp(40, 110, p), 840, p * clamp((t1 - t) / 0.3), "lm")
            words(fr, t, t0 + 0.15, t1, name, 110 + n.width - 40, 815, 104, "Black", WHITE, stagger=0.0)
            words(fr, t, t0 + 0.6, t1, sub, 110 + n.width - 30, 920, 50, "SemiBold", CREAM)
            if num == "02":  # звуковые волны дудука
                bars = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                d = ImageDraw.Draw(bars)
                for i in range(28):
                    h = 20 + 70 * abs(math.sin(t * 6 + i * 0.6)) * abs(math.sin(i * 0.37 + t))
                    x = 1180 + i * 22
                    d.rounded_rectangle((x, 900 - h, x + 10, 900 + h), 5,
                                        fill=APRICOT + (int(210 * clamp((t - t0) / 0.4) * clamp((t1 - t) / 0.3)),))
                fr.alpha_composite(bars)


# 15 · Люди 1:48–1:55
def sticker(t, dur):
    base = kenburns("C" + "Chess, Vernissage, Yerevan.jpg", t / dur, 1.0, 1.04)
    fr = base.filter(ImageFilter.GaussianBlur(14)).convert("RGBA")
    fr.alpha_composite(Image.new("RGBA", (W, H), OBSIDIAN + (110,)))
    pol = polaroid("C" + "Chess, Vernissage, Yerevan.jpg", 960, -3, 0.0)
    p = ease_back(t / 0.6)
    fr.alpha_composite(pol, (int(W / 2 - pol.width / 2 + 380), int(lerp(H, H / 2 - pol.height / 2, p))))
    return fr


seg(108.0, 113.5, sticker, xfade=0.3)
seg(113.5, 115.0, photo("Y323", 1.02, 1.08, shaded=0.0), xfade=0.25)


@ov
def people_text(fr, t):
    words(fr, t, 108.6, 113.5, "пока нет", 90, 300, 76, "Black", CREAM)
    words(fr, t, 108.9, 113.5, "покупателей —", 90, 390, 76, "Black", CREAM)
    words(fr, t, 110.0, 113.5, "партия", 90, 520, 76, "Black", APRICOT)
    words(fr, t, 110.3, 113.5, "в шахматы", 90, 610, 76, "Black", APRICOT)


# 16 · Рейтинги 1:55–2:02
RATINGS = [("Google", 4.5), ("Tripadvisor", 4.3), ("Отзовик", 4.9), ("Sputnik8", 5.0), ("Wanderboat", 4.5)]


def star_points(cx, cy, r):
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    return pts


@lru_cache(maxsize=None)
def rating_card(name, value_str, fill_frac):
    cw, ch = 300, 330
    im = Image.new("RGBA", (cw + 40, ch + 40), (0, 0, 0, 0))
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((20, 28, cw + 20, ch + 28), 28, fill=(0, 0, 0, 140))
    im = Image.alpha_composite(im, sh.filter(ImageFilter.GaussianBlur(10)))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((20, 20, cw + 20, ch + 20), 28, fill=CREAM + (255,))
    f = font(38, "Bold")
    d.text((20 + cw / 2, 75), name, font=f, fill=OBSIDIAN, anchor="mm")
    d.text((20 + cw / 2, 175), value_str, font=font(96, "Black"), fill=POM, anchor="mm")
    stars = Image.new("RGBA", im.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(stars)
    for i in range(5):
        sd.polygon(star_points(20 + 50 + i * 50, 285, 22), fill=(215, 200, 185, 255))
    filled = Image.new("RGBA", im.size, (0, 0, 0, 0))
    fd = ImageDraw.Draw(filled)
    for i in range(5):
        fd.polygon(star_points(20 + 50 + i * 50, 285, 22), fill=APRICOT + (255,))
    m = Image.new("L", im.size, 0)
    ImageDraw.Draw(m).rectangle((0, 0, 20 + 28 + fill_frac * 5 * 50 - 6, im.height), fill=255)
    stars.paste(filled, (0, 0), m)
    im.alpha_composite(stars)
    return im


def ratings_bg(t, dur):
    fr = kenburns("R750", t / dur, 1.0, 1.06).filter(ImageFilter.GaussianBlur(10))
    return darken(fr, 0.45).convert("RGBA")


seg(115.0, 122.0, ratings_bg, xfade=0.3)


@ov
def ratings(fr, t):
    if not 115.0 <= t < 122.0:
        return
    words(fr, t, 115.2, 122.0, "Оценки туристов", W // 2, 170, 72, "Black", CREAM, "m")
    for i, (name, val) in enumerate(RATINGS):
        a = 115.7 + i * 0.45
        if t < a:
            continue
        p = ease_back((t - a) / 0.5)
        cnt = clamp((t - a - 0.2) / 0.9)
        v = round(val * ease_out(cnt), 1)
        card = rating_card(name, f"{v:.1f}", round(v / 5 * 20) / 20)
        x = 120 + i * 344
        paste(fr, card, x, lerp(H + 40, 330, p), clamp((122.0 - t) / 0.3))
    s = text_sprite("данные на окт. 2026", 28, "Medium", CREAM)
    paste(fr, s, W // 2, 820, clamp((t - 118.5) / 0.5) * clamp((122.0 - t) / 0.3), "mm")


# 17 · Советы 2:02–2:10
seg(122.0, 130.0, photo("Y302", 1.0, 1.08, dark=0.35, shaded=0.4), xfade=0.3)
TIPS = ["выходные — выбор больше", "торгуйтесь вежливо", "ищите ручную работу"]


@ov
def tips(fr, t):
    if not 122.0 <= t < 130.0:
        return
    words(fr, t, 122.3, 130.0, "Советы", 160, 230, 96, "Black", APRICOT)
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    out = clamp((130.0 - t) / 0.3)
    for i, tip in enumerate(TIPS):
        a = 123.0 + i * 1.3
        y = 420 + i * 150
        if t < a:
            continue
        p = ease_out((t - a) / 0.4)
        x = 160
        box = int(255 * p * out)
        d.rounded_rectangle((x, y - 40, x + 80, y + 40), 16, outline=CREAM + (box,), width=6)
        c = clamp((t - a - 0.25) / 0.35)
        if c > 0:
            p1, p2, p3 = (x + 16, y), (x + 34, y + 22), (x + 66, y - 26)
            mid = (lerp(p1[0], p2[0], clamp(c * 2)), lerp(p1[1], p2[1], clamp(c * 2)))
            d.line((p1, mid), fill=APRICOT + (int(255 * out),), width=10)
            if c > 0.5:
                end = (lerp(p2[0], p3[0], clamp(c * 2 - 1)), lerp(p2[1], p3[1], clamp(c * 2 - 1)))
                d.line((p2, end), fill=APRICOT + (int(255 * out),), width=10)
        words(fr, t, a + 0.15, 130.0, tip, x + 120, y, 62, "ExtraBold", WHITE)
    fr.alpha_composite(lay)


# 18 · Финал 2:10–2:15
seg(130.0, 135.0, photo("R178", 1.12, 1.0, shaded=0.6, top=0.3), xfade=0.35)


@ov
def finale(fr, t):
    if not 130.0 <= t < 135.0:
        return
    s = text_sprite("ВЕРНИСАЖ", 170, "Black", CREAM)
    p = ease_out((t - 130.4) / 0.6)
    paste(fr, s, W // 2, 420 + (1 - p) * 40, p, "mm")
    words(fr, t, 131.0, 135.1, "Ереван под открытым небом", W // 2, 560, 58, "SemiBold", APRICOT, "m")
    words(fr, t, 131.6, 135.1, "м. Площадь Республики", W // 2, 650, 40, "Medium", CREAM, "m")
    chip(fr, t, 132.4, 135.1, "▶  Подпишись", W // 2, 800, 52)


# ---------------------------------------------------------------- render
DURATION = max(s[1] for s in SEG)


def frame_at(t):
    idx = next((i for i, s in enumerate(SEG) if s[0] <= t < s[1]), len(SEG) - 1)
    t0, t1, fn, xf = SEG[idx]
    fr = fn(t - t0, t1 - t0)
    if xf and t - t0 < xf and idx > 0:
        p0, p1, pfn, _ = SEG[idx - 1]
        prev = pfn(t - p0, p1 - p0)
        fr = Image.blend(prev, fr, ease_in_out((t - t0) / xf))
    fr = fr.convert("RGBA")
    for o in OV:
        o(fr, t)
    return fr.convert("RGB")


def init_worker(args):
    global A
    A = args


def render_chunk(job):
    i, f0, f1, path = job
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
           "-pix_fmt", "yuv420p", path]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in range(f0, f1):
        p.stdin.write(frame_at(f / FPS).tobytes())
    p.stdin.close()
    p.wait()
    return i


def main():
    global A
    ap = argparse.ArgumentParser()
    ap.add_argument("--google", required=True)
    ap.add_argument("--yandex", required=True)
    ap.add_argument("--commons", required=True)
    ap.add_argument("--fonts", required=True)
    ap.add_argument("-o", "--out", default="vernissage.mp4")
    ap.add_argument("--music")
    ap.add_argument("--preview")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    A = ap.parse_args()

    if A.preview:
        for s in A.preview.split(","):
            t = float(s)
            frame_at(t).save(f"{os.path.splitext(A.out)[0]}_{t:06.2f}.png")
        return

    total = int(DURATION * FPS)
    n = A.workers
    tmp = os.path.splitext(A.out)[0] + "_parts"
    os.makedirs(tmp, exist_ok=True)
    jobs = [(i, total * i // n, total * (i + 1) // n, os.path.join(tmp, f"part{i}.mp4")) for i in range(n)]
    with Pool(n, initializer=init_worker, initargs=(A,)) as pool:
        for i in pool.imap_unordered(render_chunk, jobs):
            print(f"часть {i + 1}/{n} готова", flush=True)
    lst = os.path.join(tmp, "list.txt")
    with open(lst, "w") as f:
        for j in jobs:
            f.write(f"file '{os.path.abspath(j[3])}'\n")
    audio = (["-i", A.music, "-af", f"afade=t=out:st={DURATION - 2}:d=2", "-shortest"] if A.music
             else ["-f", "lavfi", "-t", str(DURATION), "-i", "anullsrc=r=48000:cl=stereo"])
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, *audio,
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-t", str(DURATION), "-movflags", "+faststart", A.out], check=True)
    for j in jobs:
        os.remove(j[3])
    os.remove(lst)
    os.rmdir(tmp)
    print(f"Готово: {A.out} ({DURATION:.0f} с)")


if __name__ == "__main__":
    main()
