#!/usr/bin/env python3
"""Динамичный моушн‑ролик «Вернисаж. Ереван под открытым небом» (v2).

Монтаж в бит (120 BPM: доля = 0.5 с), переходы со смазом (whip, zoom‑through,
диагональная шторка, круг), тряска и вспышки на ударах, слова, залитые фото,
триптихи из вертикальных снимков, плёночное зерно и виньетка.

  --google  папка с распакованным vernissage_reviews_shortlist.zip
  --yandex  папка с распакованным vernissage_yandex_shortlist.zip
  --commons папка с фото Commons (vernissage/photos, см. download_photos.py)
  --fonts   папка с Montserrat.ttf и NotoSansArmenian.ttf (Google Fonts)

  python3 render.py --google G --yandex Y --commons C --fonts F -o vernissage.mp4
  python3 render.py ... --preview 3.0,40,98     # PNG‑кадры на этих секундах
  python3 render.py ... --range 40,52           # отрендерить только кусок
  python3 render.py ... --music track.mp3       # подложить музыку
"""
import argparse
import glob
import math
import os
import subprocess
import sys
from functools import lru_cache
from multiprocessing import Pool

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

W, H, FPS = 1920, 1080, 30
B = 0.5  # доля такта при 120 BPM
CREAM = (245, 237, 224)
TUFF = (217, 150, 122)
POM = (158, 27, 50)
APRICOT = (244, 162, 89)
OBSIDIAN = (28, 28, 30)
WHITE = (255, 255, 255)

A = None


# ================================================================ easing
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def lerp(a, b, p):
    return a + (b - a) * p


def ease_out(p):
    return 1 - (1 - clamp(p)) ** 3


def ease_in(p):
    return clamp(p) ** 3


def ease_in_out(p):
    p = clamp(p)
    return 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2


def ease_back(p):
    p = clamp(p)
    c = 1.9
    return 1 + (c + 1) * (p - 1) ** 3 + c * (p - 1) ** 2


def linear(p):
    return clamp(p)


# ================================================================ assets
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


@lru_cache(maxsize=64)
def raw(key):
    return ImageOps.exif_transpose(Image.open(find_photo(key))).convert("RGB")


@lru_cache(maxsize=None)
def font(size, weight="ExtraBold", family="Montserrat"):
    f = ImageFont.truetype(os.path.join(A.fonts, f"{family}.ttf"), size)
    f.set_variation_by_name(weight)
    return f


OVER = 1.25  # запас фото под движение камеры


@lru_cache(maxsize=32)
def cover(key):
    im = raw(key)
    tw, th = int(W * OVER), int(H * OVER)
    if im.width / im.height < 1.25:  # вертикальное — карточкой на размытом фоне
        bg = ImageOps.fit(im, (tw // 6, th // 6)).filter(ImageFilter.GaussianBlur(6)).resize((tw, th))
        bg = Image.blend(bg, Image.new("RGB", bg.size, OBSIDIAN), 0.4)
        fh = int(th * 0.82)
        fg = im.resize((int(im.width * fh / im.height), fh), Image.LANCZOS)
        bg.paste(fg, ((tw - fg.width) // 2, (th - fg.height) // 2))
        return bg
    return ImageOps.fit(im, (tw, th), Image.LANCZOS)


MOVES = {  # z0, z1, (x0, x1), (y0, y1), easing
    "push": (1.0, 1.22, (0, 0), (0, 0), ease_out),
    "pull": (1.25, 1.0, (0, 0), (0, 0), ease_out),
    "pan_l": (1.12, 1.12, (0.95, -0.95), (0, 0), ease_in_out),
    "pan_r": (1.12, 1.12, (-0.95, 0.95), (0, 0), ease_in_out),
    "rise": (1.12, 1.12, (0, 0), (0.95, -0.95), ease_in_out),
    "drift": (1.02, 1.12, (-0.3, 0.3), (0, 0), linear),
}


def cam(key, p, move="push"):
    z0, z1, px, py, ez = MOVES[move]
    img = cover(key)
    e = ez(clamp(p, 0, 1))
    z = lerp(z0, z1, e)
    cw, ch = img.width / (OVER * z), img.height / (OVER * z)
    cx = img.width / 2 + lerp(px[0], px[1], e) * (img.width - cw) / 2
    cy = img.height / 2 + lerp(py[0], py[1], e) * (img.height - ch) / 2
    return img.resize((W, H), Image.BILINEAR, box=(cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2))


@lru_cache(maxsize=None)
def shade(strength=0.55, top=0.0):
    g = np.zeros((H, 1), np.float32)
    y = np.arange(H) / H
    g[:, 0] = np.maximum(np.clip((y - 0.45) / 0.55, 0, 1) ** 1.4 * strength,
                         np.clip((0.35 - y) / 0.35, 0, 1) ** 1.4 * top)
    layer = Image.new("RGBA", (W, H), OBSIDIAN + (0,))
    layer.putalpha(Image.fromarray((np.repeat(g, W, 1) * 255).astype(np.uint8), "L"))
    return layer


def darken(img, k):
    return Image.blend(img, Image.new(img.mode, img.size, OBSIDIAN + ((255,) if img.mode == "RGBA" else ())), k)


# ================================================================ text
@lru_cache(maxsize=None)
def text_sprite(text, size, weight="ExtraBold", color=WHITE, family="Montserrat", shadow=True):
    if family == "Montserrat" and any("԰" <= ch <= "֏" for ch in text):
        family = "NotoSansArmenian"
        weight = {"Black": "ExtraBold"}.get(weight, weight)
    f = font(size, weight, family)
    ref = font(size, "Bold")
    asc, desc = ref.getmetrics()
    l, _, r, _ = f.getbbox(text, anchor="ls")
    pad = 30
    im = Image.new("RGBA", (max(1, r - l) + pad * 2, asc + desc + pad * 2), (0, 0, 0, 0))
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
    x -= {"l": 0, "m": sw // 2, "r": sw}[anchor[0]]
    y -= {"t": 0, "m": sh // 2, "b": sh}[anchor[1]]
    frame.alpha_composite(with_alpha(sprite, o), (int(x), int(y)))


def scaled(sprite, sc):
    if abs(sc - 1) < 0.01:
        return sprite
    return sprite.resize((max(1, int(sprite.width * sc)), max(1, int(sprite.height * sc))), Image.BILINEAR)


# ================================================================ timeline registry
CL = []       # клипы фона: (t0, t1, draw, transition, td)
OV = []       # оверлеи: (t0, t1, fn)
HITS = []     # удары (тряска): (t, amp)
FLASHES = []  # вспышки: (t, amp)


def clip(t0, t1, draw, trans=None, td=0.0):
    if trans == "flash":
        FLASHES.append((t0, 0.75))
        HITS.append((t0, 7))
        trans, td = None, 0.0
    CL.append((t0, t1, draw, trans, td))


def over(t0, t1, fn):
    OV.append((t0, t1, fn))


def hit(t, amp=12):
    HITS.append((t, amp))


# ================================================================ transitions
def _np(im):
    return np.asarray(im.convert("RGB"), dtype=np.uint16)


def _img(arr):
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB").convert("RGBA")


def mblur(img, k, axis=1):
    """Смаз движения: сжать картинку вдоль оси и растянуть обратно (гладкий box‑blur)."""
    if k < 3:
        return img.convert("RGBA")
    f = max(1.0, k / 5)
    small = (max(1, int(W / f)), H) if axis == 1 else (W, max(1, int(H / f)))
    return img.convert("RGB").resize(small, Image.BOX).resize((W, H), Image.BILINEAR).convert("RGBA")


def tr_whip(a, b, p, d=1):
    off = int(ease_in_out(p) * W)
    c = Image.new("RGB", (W, H))
    c.paste(a.convert("RGB"), (-off * d, 0))
    c.paste(b.convert("RGB"), ((W - off) * d, 0))
    return mblur(c, int(math.sin(math.pi * clamp(p)) * 140))


def tr_whip_r(a, b, p):
    return tr_whip(a, b, p, -1)


def tr_up(a, b, p):
    off = int(ease_in_out(p) * H)
    c = Image.new("RGB", (W, H))
    c.paste(a.convert("RGB"), (0, -off))
    c.paste(b.convert("RGB"), (0, H - off))
    return mblur(c, int(math.sin(math.pi * clamp(p)) * 110), axis=0)


def tr_zoom(a, b, p):
    k = 1 - abs(p - 0.5) * 2
    if p < 0.5:
        src, s = a, 1 + 0.7 * ease_in(p / 0.5)
    else:
        src, s = b, 1.7 - 0.7 * ease_out((p - 0.5) / 0.5)
    src = src.convert("RGB")
    n = 1 + int(k * 4)
    acc = None
    for i in range(n):
        si = s * (1 + 0.06 * k * i)
        cw, ch = W / si, H / si
        arr = np.asarray(src.resize((W, H), Image.BILINEAR,
                                    box=((W - cw) / 2, (H - ch) / 2, (W + cw) / 2, (H + ch) / 2)), np.uint16)
        acc = arr if acc is None else acc + arr
    out = acc // n
    if k > 0.5:
        out = out + ((255 - out) * int((k - 0.5) * 2 * 60)) // 100
    return _img(out)


def tr_circle(a, b, p):
    r = ease_out(p) * 1250
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).ellipse((W / 2 - r, H / 2 - r, W / 2 + r, H / 2 + r), fill=255)
    out = a.convert("RGBA").copy()
    out.paste(b.convert("RGBA"), (0, 0), m)
    if p < 0.98:
        ImageDraw.Draw(out).ellipse((W / 2 - r, H / 2 - r, W / 2 + r, H / 2 + r), outline=APRICOT + (255,), width=18)
    return out


def tr_wipe(a, b, p):
    sl = 420
    x = lerp(-900, W + sl + 200, ease_in_out(p))
    e0, e1, e2 = x - 520, x - 260, x
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).polygon([(-sl, 0), (e0 + sl, 0), (e0, H), (-sl, H)], fill=255)
    out = a.convert("RGBA").copy()
    out.paste(b.convert("RGBA"), (0, 0), m)
    d = ImageDraw.Draw(out)
    d.polygon([(e0 + sl, 0), (e1 + sl, 0), (e1, H), (e0, H)], fill=APRICOT + (255,))
    d.polygon([(e1 + sl, 0), (e2 + sl, 0), (e2, H), (e1, H)], fill=POM + (255,))
    return out


TRANS = {"whip": tr_whip, "whip_r": tr_whip_r, "up": tr_up, "zoom": tr_zoom, "circle": tr_circle, "wipe": tr_wipe}


# ================================================================ backgrounds
def solid(color):
    def draw(t, dur):
        return Image.new("RGBA", (W, H), color + (255,))
    return draw


@lru_cache(maxsize=None)
def shine_band():
    x = np.arange(900)
    band = (150 * np.exp(-((x - 450) / 140) ** 2)).astype(np.uint8)
    im = Image.fromarray(np.repeat(band[None, :], H * 2, 0), "L").rotate(20, expand=True)
    layer = Image.new("RGBA", im.size, (255, 248, 235, 0))
    layer.putalpha(im)
    return layer


def shine(frame, p):
    if 0 < p < 1:
        b = shine_band()
        frame.alpha_composite(b, (int(lerp(-b.width, W, ease_in_out(p))), (H - b.height) // 2))


def shot(key, move="push", dark=0.0, sh=0.5, top=0.0, shine_at=None):
    def draw(t, dur):
        im = cam(key, t / dur, move)
        if dark:
            im = darken(im, dark)
        fr = im.convert("RGBA")
        if sh or top:
            fr.alpha_composite(shade(sh, top))
        if shine_at is not None:
            shine(fr, (t - shine_at) / 0.9)
        return fr
    return draw


@lru_cache(maxsize=None)
def word_mask(text, size):
    f = font(size, "Black")
    while f.getbbox(text)[2] - f.getbbox(text)[0] > W * 0.9:
        size -= 10
        f = font(size, "Black")
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).text((W / 2, H / 2), text, font=f, fill=255, anchor="mm")
    return m


def maskword(key, text, bg=OBSIDIAN, size=420, move="push"):
    """Огромное слово, залитое фото."""
    def draw(t, dur):
        fr = Image.new("RGBA", (W, H), bg + (255,))
        fr.paste(cam(key, t / dur, move).convert("RGBA"), (0, 0), word_mask(text, size))
        return fr
    return draw


@lru_cache(maxsize=32)
def panel_src(key, pw, ph):
    return ImageOps.fit(raw(key), (pw, int(ph * 1.18)), Image.LANCZOS)


def panels(keys, bg=OBSIDIAN, gap=14, stagger=0.16):
    """Триптих / диптих: вертикальные фото влетают панелями сверху и снизу."""
    n = len(keys)
    pw = (W - gap * (n + 1)) // n
    ph = H - 2 * gap

    def draw(t, dur):
        fr = Image.new("RGBA", (W, H), bg + (255,))
        for i, k in enumerate(keys):
            src = panel_src(k, pw, ph)
            drift = (t / dur) if i % 2 == 0 else 1 - t / dur
            oy = int(clamp(drift) * (src.height - ph))
            tile = src.crop((0, oy, pw, oy + ph))
            p = ease_out((t - i * stagger) / 0.4)
            if p <= 0:
                continue
            dy = (1 - p) * (H if i % 2 == 0 else -H)
            fr.paste(tile, (gap + i * (pw + gap), int(gap + dy)))
        return fr
    return draw


@lru_cache(maxsize=None)
def polaroid(key, w=760, angle=0.0, sepia=0.0):
    im = ImageOps.fit(raw(key), (w, int(w * 0.75)), Image.LANCZOS)
    if sepia:
        sep = ImageOps.colorize(ImageOps.grayscale(im), (60, 40, 25), (250, 235, 205))
        im = Image.blend(im, sep, sepia)
    m = int(w * 0.05)
    card = Image.new("RGBA", (w + 2 * m, im.height + m + int(w * 0.16)), (252, 250, 245, 255))
    card.paste(im, (m, m))
    sh = Image.new("RGBA", (card.width + 100, card.height + 100), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle((50, 64, card.width + 50, card.height + 64), fill=(0, 0, 0, 120))
    sh = sh.filter(ImageFilter.GaussianBlur(20))
    sh.alpha_composite(card, (50, 50))
    return sh.rotate(angle, Image.BICUBIC, expand=True)


def land(fr, sprite, x, y, t, at, from_scale=1.45):
    """Предмет «шлёпается» на стол: масштаб 1.45→1."""
    if t < at:
        return
    p = (t - at) / 0.22
    sc = lerp(from_scale, 1.0, ease_out(p)) if p < 1 else 1.0
    paste(fr, scaled(sprite, sc), x, y, clamp(p * 3), "mm")


# ================================================================ overlays
def words(fr, t, t0, t1, text, x, y, size=72, weight="ExtraBold", color=WHITE, anchor="l", stagger=0.07, rise=0.25):
    parts = text.split(" ")
    sprites = [text_sprite(w, size, weight, color) for w in parts]
    space = int(size * 0.28) - 60
    total = sum(s.width for s in sprites) + space * (len(sprites) - 1)
    cx = {"l": x, "m": x - total // 2, "r": x - total}[anchor]
    out = clamp((t1 - t) / 0.18)
    for i, s in enumerate(sprites):
        p = ease_out((t - t0 - i * stagger) / rise)
        if p > 0:
            paste(fr, s, cx, y - s.height // 2 + (1 - p) * 60, p * out)
        cx += s.width + space


def T_words(t0, t1, text, x, y, size=72, color=WHITE, weight="ExtraBold", anchor="l", stagger=0.07):
    over(t0, t1, lambda fr, t: words(fr, t, t0, t1, text, x, y, size, weight, color, anchor, stagger))


def T_slam(t0, t1, text, x, y, size=150, color=CREAM, weight="Black", anchor="mm", amp=12):
    """Слово «влетает» из огромного размера с ударом."""
    hit(t0 + 0.16, amp)

    def fn(fr, t):
        s = text_sprite(text, size, weight, color)
        p = (t - t0) / 0.17
        sc = lerp(2.6, 1.0, ease_out(p)) if p < 1 else 1.0
        o = clamp(p * 2)
        q = (t1 - t) / 0.14
        if q < 1:
            sc *= lerp(0.8, 1.0, ease_out(q))
            o *= clamp(q)
        paste(fr, scaled(s, sc), x, y, o, anchor)
    over(t0, t1, fn)


def T_letters(t0, t1, text, x, y, size, color, step=0.08, weight="Black"):
    """Буквы падают по одной с ударом."""
    for i in range(len(text)):
        hit(t0 + i * step + 0.14, 4)

    def fn(fr, t):
        sprites = [text_sprite(ch, size, weight, color) for ch in text]
        adv = [s.width - 60 for s in sprites]
        cx = x - sum(adv) // 2
        q = clamp((t1 - t) / 0.15)
        for i, s in enumerate(sprites):
            p = (t - t0 - i * step) / 0.16
            if p > 0:
                sc = lerp(2.2, 1.0, ease_out(p)) if p < 1 else 1.0
                paste(fr, scaled(s, sc), cx + adv[i] // 2 + 30, y, clamp(p * 2) * q, "mm")
            cx += adv[i]
    over(t0, t1, fn)


@lru_cache(maxsize=None)
def bar_img(w, h, color):
    return Image.new("RGBA", (w, h), color + (255,))


def T_bar(t0, t1, text, x, y, size=56, bg=POM, fg=WHITE, weight="ExtraBold", anchor="l"):
    """Плашка вырастает слева, текст выезжает за ней; уходит, схлопываясь вправо."""
    def fn(fr, t):
        s = text_sprite(text, size, weight, fg, shadow=False)
        padx = int(size * 0.5)
        bw, bh = s.width - 60 + padx * 2, int(size * 1.45)
        bx = {"l": x, "m": x - bw // 2, "r": x - bw}[anchor]
        p = ease_out((t - t0) / 0.26)
        q = ease_in_out(clamp((t1 - t) / 0.22))
        if q < 1:
            left = bx + int(bw * (1 - q))
            w = bx + bw - left
        else:
            left, w = bx, int(bw * p)
        if w > 1:
            fr.alpha_composite(bar_img(w, bh, bg), (int(left), int(y - bh // 2)))
        tp = ease_out((t - t0 - 0.12) / 0.25)
        if tp > 0 and q > 0.3:
            bx0 = int(bx + padx - 30 - (1 - tp) * 40)
            by0 = int(y - s.height // 2)
            cl = max(0, int(left - bx0))
            cr = min(s.width, int(left + w - bx0))
            if cr > cl:
                fr.alpha_composite(with_alpha(s.crop((cl, 0, cr, s.height)), tp), (bx0 + cl, by0))
    over(t0, t1, fn)


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


def T_chip(t0, t1, text, x, y, size=50, bg=POM, fg=WHITE):
    hit(t0 + 0.2, 5)

    def fn(fr, t):
        s = chip_sprite(text, size, bg, fg)
        p = ease_back((t - t0) / 0.3)
        o = clamp((t - t0) / 0.12) * clamp((t1 - t) / 0.18)
        paste(fr, scaled(s, lerp(0.3, 1.0, p)), x, y, o, "mm")
    over(t0, t1, fn)


# ================================================================ SCENES (1:52)
# ---- 1 · Интро 0:00–0:08: 8 кадров в бит со вспышками → слово из фото → арки
INTRO = [("R648", "push"), ("Y343", "pan_l"), ("R165", "pull"), ("R734", "push"),
         ("R542", "pan_r"), ("Y116", "push"), ("R857", "pull"), ("Y083", "pan_l")]
for i, (k, mv) in enumerate(INTRO):
    clip(i * B, (i + 1) * B, shot(k, mv, sh=0.15), "flash" if i else None)
clip(4.0, 6.0, maskword("R290", "ВЕРНИСАЖ", OBSIDIAN, 420, "drift"), "zoom", 0.3)
hit(4.15, 16)
clip(6.0, 8.0, shot("R290", "pull", sh=0.6), "circle", 0.4)
T_slam(6.2, 8.0, "ВЕРНИСАЖ", W // 2, H // 2 - 20, 190)
T_words(6.6, 8.0, "Ереван · Երևան", W // 2, H // 2 + 130, 48, CREAM, "SemiBold", "m")


# ---- 2 · Ереван на карте 0:08–0:14
def map_bg(t, dur):
    fr = Image.new("RGBA", (W, H), OBSIDIAN + (255,))
    d = ImageDraw.Draw(fr)
    z = 1 + 4 * ease_in(t / dur)
    step = 120 * z
    ox, oy = (W / 2) % step, (H / 2) % step
    for i in range(-2, int(W / step) + 3):
        d.line((ox + i * step, 0, ox + i * step, H), fill=(62, 56, 56, 255), width=1)
    for i in range(-2, int(H / step) + 3):
        d.line((0, oy + i * step, W, oy + i * step), fill=(62, 56, 56, 255), width=1)
    rings = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rings)
    for k in range(3):
        r = (t * 420 + k * 200) % 600
        rd.ellipse((W / 2 - r, H / 2 - r, W / 2 + r, H / 2 + r), outline=APRICOT + (int(220 * (1 - r / 600)),), width=4)
    fr.alpha_composite(rings)
    p = ease_back((t - 0.15) / 0.35)
    if t > 0.15:
        cx, py = W / 2, lerp(H / 2 - 260, H / 2 - 70, p)
        d.ellipse((cx - 26, py - 26, cx + 26, py + 26), fill=POM + (255,))
        d.polygon([(cx - 19, py + 14), (cx + 19, py + 14), (cx, py + 70)], fill=POM + (255,))
        d.ellipse((cx - 9, py - 9, cx + 9, py + 9), fill=CREAM + (255,))
    return fr


clip(8.0, 11.0, map_bg, "whip", 0.3)
hit(8.45, 10)
T_slam(8.6, 11.0, "ЕРЕВАН", W // 2, H // 2 + 120, 130)
over(9.0, 11.0, lambda fr, t: paste(fr, text_sprite("40.17° N · 44.51° E"[:int((t - 9.0) * 40)] or " ", 40, "Medium", APRICOT),
                                    W // 2, H // 2 + 230, clamp((11.0 - t) / 0.2), "mm"))
clip(11.0, 14.0, shot("R026", "push", sh=0.65), "zoom", 0.4)
T_words(11.4, 14.0, "вся Армения —", W // 2, 790, 80, WHITE, "ExtraBold", "m")
T_slam(12.0, 14.0, "ЗА ОДИН ЧАС", W // 2, 900, 120, APRICOT)

# ---- 3 · Вход и ряды 0:14–0:22
clip(14.0, 15.0, shot("Y058", "push", sh=0.3), "whip", 0.25)
clip(15.0, 16.0, shot("R008", "pan_r", sh=0.3), "whip", 0.25)
clip(16.0, 19.0, shot("R554", "pan_l", sh=0.55), "whip_r", 0.25)
T_chip(16.4, 19.0, "~1000 продавцов", 520, 860, 54)
T_chip(16.9, 19.0, "350 м рядов", 960, 950, 54, APRICOT, OBSIDIAN)
T_chip(17.4, 19.0, "вход бесплатный", 1400, 860, 54, CREAM, POM)
clip(19.0, 22.0, panels(["R135", "Y329", "R041"]), None)
T_bar(19.6, 22.0, "каждый день · под открытым небом", W // 2, 940, 56, POM, WHITE, anchor="m")

# ---- 4 · Слово «вернисаж» 0:22–0:30
clip(22.0, 24.5, solid(POM), "wipe", 0.45)
T_letters(22.3, 24.5, "VERNISSAGE", W // 2, H // 2 - 40, 190, CREAM)
T_words(23.4, 24.5, "(фр.)", W // 2, H // 2 + 110, 54, APRICOT, "SemiBold", "m")
clip(24.5, 27.5, shot("R175", "pan_l", sh=0.7, shine_at=0.3), "zoom", 0.35)
T_bar(24.8, 27.5, "показ картин", 140, 800, 80, POM, WHITE, "Black")
T_words(25.2, 27.5, "до открытия выставки", 140, 910, 60, CREAM, "Bold")
clip(27.5, 30.0, shot("R028", "push", sh=0.7), "whip", 0.25)
T_words(27.8, 30.0, "в Ереване —", 140, 790, 76, WHITE, "ExtraBold")
T_slam(28.3, 30.0, "С КОНЦА 1970‑Х", 140, 900, 104, APRICOT, anchor="lm")

# ---- 5–6 · История 0:30–0:42: счётчик лет, полароиды шлёпаются на стол
HIST = [  # (время относительно 30.0, фото, x, y, ширина, угол)
    (0.7, "CArmenia, Yerevan (2166087660).jpg", 1390, 470, 700, -5),
    (6.4, "CErevan - Vernissage 01.JPG", 1210, 330, 520, 6),
    (6.9, "CErevan - Vernissage 02.JPG", 1560, 430, 520, -7),
    (8.4, "CYerevan Vernissage view.jpg", 1350, 640, 560, 3),
]
for at, *_ in HIST:
    hit(30.0 + at + 0.2, 13)
YEARS = [(0.0, 1970, 1980, "‑е"), (6.0, 1980, 1988, ""), (8.0, 1988, 1990, "‑е")]


def history(t, dur):
    fr = Image.new("RGBA", (W, H), CREAM + (255,))
    d = ImageDraw.Draw(fr)
    for i in range(0, W + H, 90):  # лёгкая диагональная фактура
        d.line((i, 0, i - H, H), fill=(238, 228, 212, 255), width=2)
    for at, key, x, y, w, ang in HIST:
        land(fr, polaroid(key, w, ang, 0.45), x, y, t, at)
    return fr


clip(30.0, 40.0, history, "up", 0.4)


def year_counter(fr, t):
    lt = t - 30.0
    cur = None
    for at, a, b, suf in YEARS:
        if lt >= at:
            v = int(round(lerp(a, b, ease_out((lt - at) / 0.5))))
            cur = (v, suf if v == b else "", at)
    v, suf, at = cur
    s = text_sprite(f"{v}{suf}", 210, "Black", POM, shadow=False)
    p = (lt - at) / 0.5
    sc = 1.0 + (0.12 * (1 - ease_out((p - 1) / 0.3)) if 1 <= p < 1.3 else 0)
    paste(fr, scaled(s, sc), 110, 250, clamp(lt / 0.2) * clamp((40.0 - t) / 0.2), "lm")
    marks = [1970, 1980, 1988, 1990]
    xs = [140 + i * 240 for i in range(4)]
    dr = ImageDraw.Draw(fr)
    dr.line((110, 1000, 900, 1000), fill=TUFF + (255,), width=4)
    pos = float(np.interp(v, marks, xs))
    dr.line((110, 1000, pos, 1000), fill=POM + (255,), width=9)
    for x, m in zip(xs, marks):
        on = abs(pos - x) < 3
        r = 15 if on else 8
        dr.ellipse((x - r, 1000 - r, x + r, 1000 + r), fill=(POM if on else TUFF) + (255,))
        paste(fr, text_sprite(str(m), 30 if on else 26, "Bold" if on else "Medium", POM if on else (130, 100, 85), shadow=False),
              x, 960, 1.0, "mb")


over(30.0, 40.0, year_counter)
T_words(31.0, 36.0, "художники выставляют", 120, 430, 58, OBSIDIAN, "Bold")
T_words(31.3, 36.0, "картины прямо на улице", 120, 505, 58, OBSIDIAN, "Bold")
T_bar(32.8, 36.0, "не рынок — выставка", 120, 650, 60, POM, WHITE)
T_words(33.2, 36.0, "под открытым небом", 120, 745, 54, OBSIDIAN, "Bold")
T_words(36.3, 40.0, "приходят резчики,", 120, 430, 58, OBSIDIAN, "Bold")
T_words(36.6, 40.0, "ювелиры, ткачи", 120, 505, 58, OBSIDIAN, "Bold")
T_bar(38.6, 40.0, "рынок, который кормит мастеров", 120, 650, 54, POM, WHITE)
over(30.0, 40.0, lambda fr, t: paste(fr, text_sprite("архивные фото 2005–2007", 24, "Medium", (130, 100, 85), shadow=False),
                                     1800, 1040, clamp((t - 31) / 0.4) * clamp((40 - t) / 0.2), "rm"))
clip(40.0, 42.0, shot("CYerevan Vernissage by ArmAg (1).jpg", "push", sh=0.6), "zoom", 0.35)
T_slam(40.3, 42.0, "2016", W // 2, 780, 170, APRICOT)
T_words(40.7, 42.0, "новые павильоны", W // 2, 910, 62, WHITE, "ExtraBold", "m")


# ---- 7 · Сквер Сарьяна ↔ площадь Республики 0:42–0:46 (сплит‑экран)
def split2(t, dur):
    fr = Image.new("RGBA", (W, H), OBSIDIAN + (255,))
    for i, k in enumerate(["C2025-05-18 Yerevan, Saryan park.jpg", "R026"]):
        src = panel_src(k, W // 2 - 10, H)
        oy = int(clamp(t / dur if i == 0 else 1 - t / dur) * (src.height - H))
        tile = src.crop((0, oy, W // 2 - 10, oy + H))
        p = ease_out((t - i * 0.15) / 0.4)
        dy = (1 - p) * (-H if i == 0 else H)
        fr.paste(tile, (i * (W // 2 + 10), int(dy)))
    fr.alpha_composite(shade(0.6))
    ImageDraw.Draw(fr).rectangle((W // 2 - 10, 0, W // 2 + 10, H), fill=APRICOT + (255,))
    return fr


clip(42.0, 46.0, split2, None)
T_bar(42.6, 46.0, "художники", W // 4, 820, 64, POM, WHITE, "Black", "m")
T_words(42.9, 46.0, "сквер Сарьяна", W // 4, 920, 50, CREAM, "Bold", "m")
T_bar(43.1, 46.0, "рынок", 3 * W // 4, 820, 64, POM, WHITE, "Black", "m")
T_words(43.4, 46.0, "площадь Республики", 3 * W // 4, 920, 50, CREAM, "Bold", "m")


# ---- 8 · Что здесь искать 0:46–0:50
def reveal(t, dur):
    fr = Image.new("RGBA", (W, H), POM + (255,))
    img = darken(cam("Y371", t / dur, "drift"), 0.45).convert("RGBA")
    r = ease_out((t - 0.05) / 0.6) * 1250
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).ellipse((W / 2 - r, H / 2 - r, W / 2 + r, H / 2 + r), fill=255)
    fr.paste(img, (0, 0), m)
    return fr


clip(46.0, 50.0, reveal, "flash")
T_slam(46.4, 50.0, "ЧТО ЗДЕСЬ ИСКАТЬ", W // 2, H // 2 - 20, 140, amp=16)
T_words(47.0, 50.0, "6 вещей, за которыми сюда едут", W // 2, H // 2 + 115, 46, APRICOT, "SemiBold", "m")

# ---- 9–14 · Каталог 0:50–1:26: слово из фото → кадры в бит → триптих
CATALOG = [
    ("01", "КОВРЫ", "ручная работа", "R648", POM,
     [("R164", "pan_r", 1.25), ("Y343", "push", 1.25), (["R836", "Y174", "R027"], None, 2.0)]),
    ("02", "ДУДУК", "абрикосовое дерево", "Y083", OBSIDIAN,
     [("Y083", "pan_l", 1.5), ("CVernissage, Erevan, Arménie - duduk.JPG", "push", 1.0), (["Y008", "R033"], None, 2.0)]),
    ("03", "НАРДЫ", "с Араратом на крышке", "R108", APRICOT,
     [("R734", "push", 1.0), ("Y354", "pan_r", 1.0), ("Y015", "pull", 1.25), ("R857", "push", 1.25)]),
    ("04", "ГРАНАТ", "символ Армении", "R378", POM,
     [("Y116", "pan_l", 1.25), ("R378", "push", 1.25), (["R744", "R392", "Y136"], None, 2.0)]),
    ("05", "ОБСИДИАН", "вулканическое стекло", "Y236", OBSIDIAN,
     [("R070", "push", 1.25), ("Y236", "pan_r", 1.25), (["R867", "R748", "R693"], None, 2.0)]),
    ("06", "АНТИКВАРИАТ", "машина времени", "R824", APRICOT,
     [("R824", "push", 0.75), ("R542", "pan_r", 0.75), ("Y219", "push", 0.75), ("R584", "pull", 0.75),
      (["R460", "R153", "R328"], None, 1.5)]),
]
TR_CYCLE = ["whip", "flash", "whip_r", "flash"]
t = 50.0
for num, name, sub, mkey, bg, shots in CATALOG:
    t0 = t
    clip(t, t + 1.5, maskword(mkey, name, bg, 400, "drift"), "wipe" if num != "01" else "zoom", 0.4)
    T_slam(t + 0.25, t + 1.5, num, 170, 170, 120, CREAM, anchor="lm", amp=6)
    hit(t + 0.3, 14)
    t += 1.5
    for i, (k, mv, dur) in enumerate(shots):
        tr = "zoom" if i == 0 else TR_CYCLE[(i + int(num)) % 4]
        if isinstance(k, list):
            clip(t, t + dur, panels(k), None)
        else:
            clip(t, t + dur, shot(k, mv, sh=0.6, shine_at=0.2 if num == "05" and i == 0 else None),
                 tr, 0.0 if tr == "flash" else (0.4 if tr == "zoom" else 0.25))
        t += dur
    T_bar(t0 + 1.8, t - 0.05, f"{num}  {name}", 110, 860, 66, bg if bg != OBSIDIAN else POM, WHITE, "Black")
    T_words(t0 + 2.1, t - 0.05, sub, 110, 960, 46, CREAM, "Bold")
    if name == "ДУДУК":
        def eq(fr, tt, t_a=t0 + 1.5, t_b=t):
            bars = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(bars)
            o = clamp((tt - t_a) / 0.3) * clamp((t_b - tt) / 0.2)
            for i in range(34):
                h = 18 + 95 * abs(math.sin(tt * 9 + i * 0.55)) * abs(math.sin(i * 0.31 + tt * 2))
                x = 1060 + i * 24
                d.rounded_rectangle((x, 900 - h, x + 12, 900 + h), 6, fill=APRICOT + (int(220 * o),))
            fr.alpha_composite(bars)
        over(t0 + 1.5, t, eq)
assert abs(t - 86.0) < 1e-6, t


# ---- 15 · Люди 1:26–1:32
def sticker(t, dur):
    key = "CChess, Vernissage, Yerevan.jpg"
    fr = cam(key, t / dur, "drift").filter(ImageFilter.GaussianBlur(16)).convert("RGBA")
    fr.alpha_composite(Image.new("RGBA", (W, H), OBSIDIAN + (120,)))
    land(fr, polaroid(key, 940, -4, 0.0), W / 2 + 330, H / 2, t, 0.1, 1.6)
    return fr


clip(86.0, 90.5, sticker, "whip", 0.3)
hit(86.32, 16)
T_slam(86.5, 90.5, "ПОКА НЕТ", 110, 330, 92, CREAM, anchor="lm", amp=6)
T_slam(86.8, 90.5, "ПОКУПАТЕЛЕЙ —", 110, 440, 92, CREAM, anchor="lm", amp=6)
T_bar(87.6, 90.5, "партия в шахматы", 110, 590, 66, APRICOT, OBSIDIAN, "Black")
clip(90.5, 92.0, shot("Y323", "push", sh=0.0), "flash")

# ---- 16 · Рейтинги 1:32–1:40
RATINGS = [("Google", 4.5), ("Tripadvisor", 4.3), ("Отзовик", 4.9), ("Sputnik8", 5.0), ("Wanderboat", 4.5)]


def star_points(cx, cy, r):
    return [(cx + (r if i % 2 == 0 else r * 0.45) * math.cos(-math.pi / 2 + i * math.pi / 5),
             cy + (r if i % 2 == 0 else r * 0.45) * math.sin(-math.pi / 2 + i * math.pi / 5)) for i in range(10)]


@lru_cache(maxsize=None)
def rating_card(name, value_str, fill_frac):
    cw, ch = 300, 330
    im = Image.new("RGBA", (cw + 40, ch + 40), (0, 0, 0, 0))
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((20, 28, cw + 20, ch + 28), 28, fill=(0, 0, 0, 140))
    im = Image.alpha_composite(im, sh.filter(ImageFilter.GaussianBlur(10)))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((20, 20, cw + 20, ch + 20), 28, fill=CREAM + (255,))
    d.text((20 + cw / 2, 75), name, font=font(38, "Bold"), fill=OBSIDIAN, anchor="mm")
    d.text((20 + cw / 2, 175), value_str, font=font(96, "Black"), fill=POM, anchor="mm")
    stars = Image.new("RGBA", im.size, (0, 0, 0, 0))
    filled = Image.new("RGBA", im.size, (0, 0, 0, 0))
    for i in range(5):
        ImageDraw.Draw(stars).polygon(star_points(70 + i * 50, 285, 22), fill=(215, 200, 185, 255))
        ImageDraw.Draw(filled).polygon(star_points(70 + i * 50, 285, 22), fill=APRICOT + (255,))
    m = Image.new("L", im.size, 0)
    ImageDraw.Draw(m).rectangle((0, 0, 48 + fill_frac * 250 - 6, im.height), fill=255)
    stars.paste(filled, (0, 0), m)
    im.alpha_composite(stars)
    return im


def ratings_bg(t, dur):
    fr = cam("R750", t / dur, "drift").filter(ImageFilter.GaussianBlur(12))
    return darken(fr, 0.5).convert("RGBA")


clip(92.0, 100.0, ratings_bg, "zoom", 0.35)
T_slam(92.3, 100.0, "ОЦЕНКИ ТУРИСТОВ", W // 2, 175, 84, CREAM, amp=8)
for i in range(5):
    hit(92.9 + i * B + 0.22, 9)


def ratings(fr, t):
    for i, (name, val) in enumerate(RATINGS):
        a = 92.9 + i * B
        if t < a:
            continue
        p = (t - a) / 0.3
        v = round(val * ease_out((t - a - 0.1) / 0.8), 1)
        card = rating_card(name, f"{v:.1f}", round(v / 5 * 20) / 20)
        flip = abs(math.cos((1 - ease_out(p)) * math.pi / 2)) if p < 1 else 1.0
        c = card.resize((max(1, int(card.width * flip)), card.height), Image.BILINEAR) if flip < 0.99 else card
        x = 120 + i * 344 + card.width // 2
        y = lerp(240, 330, ease_out(p)) + card.height // 2
        paste(fr, c, x, y, clamp(p * 3) * clamp((100.0 - t) / 0.2), "mm")
    paste(fr, text_sprite("данные на окт. 2026", 28, "Medium", CREAM), W // 2, 820,
          clamp((t - 95.5) / 0.4) * clamp((100.0 - t) / 0.2), "mm")


over(92.0, 100.0, ratings)

# ---- 17 · Советы 1:40–1:46: на каждый совет — свой кадр и «галочка» в бит
TIPS = [("R660", "push", "выходные — выбор больше"), ("Y302", "pan_l", "торгуйтесь вежливо"),
        ("R079", "push", "ищите ручную работу")]


@lru_cache(maxsize=None)
def check_sprite():
    im = Image.new("RGBA", (190, 190), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((10, 10, 180, 180), 34, fill=APRICOT + (255,))
    d.line([(52, 98), (84, 132), (140, 62)], fill=OBSIDIAN + (255,), width=20, joint="curve")
    return im


for i, (k, mv, tip) in enumerate(TIPS):
    a = 100.0 + i * 2.0
    clip(a, a + 2.0, shot(k, mv, dark=0.25, sh=0.6), "whip" if i else "circle", 0.25 if i else 0.4)
    hit(a + 0.35, 12)
    over(a, a + 1.85, lambda fr, t, a=a: land(fr, check_sprite(), 230, H // 2 + 60, t, a + 0.15, 2.0))
    T_slam(a + 0.35, a + 1.9, tip, 380, H // 2 + 60, 84, WHITE, anchor="lm", amp=4)
T_bar(100.3, 105.9, "СОВЕТЫ", 140, 230, 64, POM, WHITE, "Black")

# ---- 18 · Финал 1:46–1:52
clip(106.0, 112.0, shot("R178", "pull", sh=0.6, top=0.3), "zoom", 0.4)
T_slam(106.4, 111.6, "ВЕРНИСАЖ", W // 2, 420, 190, CREAM, amp=16)
T_words(107.0, 111.6, "Ереван под открытым небом", W // 2, 560, 60, APRICOT, "SemiBold", "m")
T_words(107.5, 111.6, "м. Площадь Республики", W // 2, 650, 42, CREAM, "Medium", "m")
T_chip(108.2, 111.6, "▶  Подпишись", W // 2, 800, 56)
over(110.8, 112.0, lambda fr, t: fr.alpha_composite(Image.new("RGBA", (W, H), (0, 0, 0, int(255 * ease_in_out((t - 110.8) / 1.0))))))

DURATION = 112.0


# ================================================================ compositing
def background(t):
    idx = next((i for i, c in enumerate(CL) if c[0] <= t < c[1]), len(CL) - 1)
    t0, t1, fn, tr, td = CL[idx]
    fr = fn(t - t0, t1 - t0).convert("RGBA")
    if tr and t - t0 < td and idx > 0:
        p0, p1, pfn, _, _ = CL[idx - 1]
        fr = TRANS[tr](pfn(t - p0, p1 - p0), fr, (t - t0) / td)
    return fr


def shake(t):
    dx = dy = 0.0
    for h, amp in HITS:
        u = t - h
        if 0 <= u < 0.4:
            k = amp * math.exp(-u * 11)
            dx += k * math.sin(u * 95 + h * 7)
            dy += k * math.cos(u * 83 + h * 3)
    return dx, dy


_FX = {}


def fx():
    if not _FX:
        y, x = np.mgrid[0:H, 0:W].astype(np.float32)
        r = ((x - W / 2) / (W / 2)) ** 2 + ((y - H / 2) / (H / 2)) ** 2
        _FX["vig"] = (1 - 0.32 * np.clip(r, 0, 1.6) ** 1.3)[..., None].astype(np.float32)
        rng = np.random.default_rng(7)
        _FX["grain"] = [rng.normal(0, 5.5, (H, W, 1)).astype(np.float32) for _ in range(6)]
    return _FX


def frame_at(t):
    fr = background(t)
    for a, b, fn in OV:
        if a <= t < b:
            fn(fr, t)
    for h, amp in FLASHES:
        u = t - h
        if 0 <= u < 0.14:
            fr.alpha_composite(Image.new("RGBA", (W, H), (255, 250, 240, int(255 * amp * (1 - u / 0.14) ** 2))))
    img = fr.convert("RGB")
    dx, dy = shake(t)
    if abs(dx) + abs(dy) > 0.6:
        m = max(abs(dx), abs(dy)) + 2
        img = img.resize((W, H), Image.BILINEAR, box=(m + dx, m + dy, W - m + dx, H - m + dy))
    f = fx()
    arr = np.asarray(img, np.float32) * f["vig"] + f["grain"][int(t * FPS) % 6]
    return np.clip(arr, 0, 255).astype(np.uint8)


def init_worker(args):
    global A
    A = args


def render_chunk(job):
    i, f0, f1, path = job
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "17",
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
    ap.add_argument("--range")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    A = ap.parse_args()

    if A.preview:
        for s in A.preview.split(","):
            t = float(s)
            Image.fromarray(frame_at(t)).save(f"{os.path.splitext(A.out)[0]}_{t:06.2f}.png")
        return

    start, end = (map(float, A.range.split(","))) if A.range else (0.0, DURATION)
    f_start, f_end = int(start * FPS), int(end * FPS)
    n = A.workers
    tmp = os.path.splitext(A.out)[0] + "_parts"
    os.makedirs(tmp, exist_ok=True)
    total = f_end - f_start
    jobs = [(i, f_start + total * i // n, f_start + total * (i + 1) // n, os.path.join(tmp, f"part{i}.mp4"))
            for i in range(n)]
    with Pool(n, initializer=init_worker, initargs=(A,)) as pool:
        for i in pool.imap_unordered(render_chunk, jobs):
            print(f"часть {i + 1}/{n} готова", flush=True)
    lst = os.path.join(tmp, "list.txt")
    with open(lst, "w") as f:
        for j in jobs:
            f.write(f"file '{os.path.abspath(j[3])}'\n")
    length = (f_end - f_start) / FPS
    audio = (["-ss", str(start), "-i", A.music, "-af", f"afade=t=out:st={max(0, length - 2)}:d=2"] if A.music
             else ["-f", "lavfi", "-t", str(length), "-i", "anullsrc=r=48000:cl=stereo"])
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, *audio,
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-t", str(length), "-movflags", "+faststart", A.out], check=True)
    for j in jobs:
        os.remove(j[3])
    os.remove(lst)
    os.rmdir(tmp)
    print(f"Готово: {A.out} ({length:.1f} с)")


if __name__ == "__main__":
    main()
