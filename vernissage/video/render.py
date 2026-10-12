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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import space  # noqa: E402

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


def clip(t0, t1, draw, trans=None, td=0.0, prev=None):
    if trans == "flash":
        FLASHES.append((t0, 0.75))
        HITS.append((t0, 7))
        trans, td = None, 0.0
    CL.append((t0, t1, draw, trans, td, prev))


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
# ---- 1 · Интро 0:00–0:08: 8 самых ярких кадров в бит → стеклянное VERNISSAGE / YEREVAN
INTRO = [("Y169", "push"), ("R819", "pan_l"), ("R755", "pull"), ("Y149", "push"),
         ("R842", "pan_r"), ("Y336", "push"), ("R743", "pull"), ("R816", "pan_l")]
for i, (k, mv) in enumerate(INTRO):
    clip(i * B, (i + 1) * B, shot(k, mv, sh=0.1), "flash" if i else None)
MARQ = ["Y116", "Y067", "R348", "Y321", "R378", "R840", "Y129", "R682", "Y171", "R666", "Y340", "R498",
        "R756", "R857", "Y383", "R842"]


@lru_cache(maxsize=None)
def marq_tile(key, w=540, h=360):
    from PIL import ImageEnhance
    im = ImageOps.fit(raw(key), (w, h), Image.LANCZOS)
    im = ImageEnhance.Color(im).enhance(1.3)
    return ImageEnhance.Brightness(im).enhance(1.08)


@lru_cache(maxsize=None)
def pomegranate(size=240):
    """Векторный гранат: глянцевый шар, блик и корона."""
    n = size
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32) / n
    cx, cy, r = 0.5, 0.56, 0.4
    d = np.hypot(xx - cx, yy - cy) / r
    hl = np.hypot(xx - (cx - 0.13), yy - (cy - 0.15)) / r
    body = np.clip(1 - d, 0, 1)
    a = np.clip((1 - d) * n * 0.08, 0, 1)
    t = np.clip(hl / 1.6, 0, 1)
    col = np.stack([lerp(245, 110, t), lerp(60, 8, t), lerp(70, 22, t)], -1)
    im = Image.fromarray(np.dstack([col, a * 255]).astype(np.uint8), "RGBA")
    dr = ImageDraw.Draw(im)
    c = n / 2
    crown = [(c - 0.11 * n, 0.2 * n), (c - 0.13 * n, 0.07 * n), (c - 0.05 * n, 0.14 * n), (c, 0.04 * n),
             (c + 0.05 * n, 0.14 * n), (c + 0.13 * n, 0.07 * n), (c + 0.11 * n, 0.2 * n)]
    dr.polygon(crown, fill=(150, 22, 38, 255))
    spec = Image.new("L", (n, n), 0)
    ImageDraw.Draw(spec).ellipse((0.27 * n, 0.32 * n, 0.43 * n, 0.44 * n), fill=170)
    spec = spec.filter(ImageFilter.GaussianBlur(n * 0.03))
    im.alpha_composite(Image.merge("RGBA", (Image.new("L", (n, n), 255),) * 3 + (spec,)))
    return im


def flag(t, w=300, h=200, phase=0.0):
    """Армянский флаг, развевающийся на ветру."""
    base = np.zeros((h, w, 3), np.float32)
    base[: h // 3] = (217, 0, 18)
    base[h // 3: 2 * h // 3] = (0, 51, 160)
    base[2 * h // 3:] = (242, 168, 0)
    A = h * 0.08
    xs = np.arange(w) / w
    wave = np.sin(2 * np.pi * (xs * 1.3 - t * 1.2) + phase)
    dy = (A * wave * xs).astype(np.int32)
    shade = 1 + 0.22 * np.cos(2 * np.pi * (xs * 1.3 - t * 1.2) + phase) * xs
    out = np.zeros((h + int(2 * A) + 2, w + 10, 4), np.uint8)
    for x in range(w):
        y0 = int(A) + 1 + dy[x]
        out[y0:y0 + h, x + 10, :3] = np.clip(base[:, x] * shade[x], 0, 255)
        out[y0:y0 + h, x + 10, 3] = 255
    out[:, 2:7, :3] = (60, 50, 45)  # древко
    out[:, 2:7, 3] = 255
    return Image.fromarray(out, "RGBA")


STICK = []  # (тип, x0, y0, vx, vy, масштаб, вращение, фаза)
_rng = np.random.default_rng(3)
for _i in range(14):
    STICK.append(("pom" if _i % 2 == 0 else "flag", float(_rng.uniform(-100, W + 100)), float(_rng.uniform(40, H - 40)),
                  float(_rng.choice([-1, 1]) * _rng.uniform(60, 160)), float(_rng.uniform(-40, 40)),
                  float(_rng.uniform(0.55, 1.15)), float(_rng.uniform(-40, 40)), float(_rng.uniform(0, 6))))


@lru_cache(maxsize=None)
def title_band():
    """Мягкое затемнение под заголовком — чтобы стекло читалось на пёстром фоне."""
    y = np.arange(H, dtype=np.float32)
    a = np.exp(-((y - (H / 2 + 10)) / 230) ** 2) * 150
    m = Image.fromarray(np.repeat(a[:, None], W, 1).astype(np.uint8), "L")
    band = Image.new("RGBA", (W, H), (25, 8, 14, 0))
    band.putalpha(m)
    return band


@lru_cache(maxsize=None)
def title_masks(scale_q):
    sc = scale_q / 100
    big = Image.new("L", (W, H), 0)
    size = 300
    while font(size, "Black").getlength("VERNISSAGE") > W * 0.9:
        size -= 6
    f = font(int(size * sc), "Black")
    ImageDraw.Draw(big).text((W / 2, H / 2 - 110), "VERNISSAGE", font=f, fill=255, anchor="mm")
    small = Image.new("L", (W, H), 0)
    fs = font(int(190 * sc), "Black")
    ds = ImageDraw.Draw(small)
    letters, track = "YEREVAN", int(40 * sc)
    widths = [fs.getbbox(ch)[2] - fs.getbbox(ch)[0] for ch in letters]
    x = W / 2 - (sum(widths) + track * (len(letters) - 1)) / 2
    for ch, wd in zip(letters, widths):
        ds.text((x, H / 2 + 170), ch, font=fs, fill=255, anchor="lm")
        x += wd + track
    return big, small


def glass(fr, mask, o):
    """«Стеклянный» текст: под буквами — размытый и осветлённый фон, белая кромка, тень."""
    if o <= 0:
        return
    m = np.asarray(mask, np.float32)[..., None] / 255 * o
    sh = np.asarray(mask.filter(ImageFilter.GaussianBlur(14)), np.float32)[..., None] / 255 * o
    sh = np.roll(np.roll(sh, 10, 0), 6, 1)
    rgb = np.asarray(fr.convert("RGB"), np.float32)
    rgb = rgb * (1 - 0.45 * sh)
    blur = np.asarray(fr.convert("RGB").filter(ImageFilter.GaussianBlur(20)), np.float32)
    frost = blur * 0.62 + 255 * 0.38
    rgb = rgb * (1 - m) + frost * m
    edge = np.asarray(mask.filter(ImageFilter.MaxFilter(5)), np.float32)[..., None] / 255 - np.asarray(mask, np.float32)[..., None] / 255
    rgb = rgb * (1 - np.clip(edge, 0, 1) * 0.9 * o) + 255 * np.clip(edge, 0, 1) * 0.9 * o
    fr.paste(Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)).convert("RGBA"))


def market_layer(t):
    """Цветной «рынок»: ленты ярких фото едут навстречу, летят гранаты и флаги."""
    fr = Image.new("RGBA", (W, H), OBSIDIAN + (255,))
    tw, th, gap = 540, 360, 8
    for row in range(3):
        speed = (130, -170, 110)[row]
        off = (t * speed + row * 200) % ((tw + gap) * len(MARQ))
        x = -off
        k = row * 5
        while x < W:
            if x + tw > 0:
                fr.paste(marq_tile(MARQ[k % len(MARQ)]), (int(x), row * (th + gap) - 30))
            x += tw + gap
            k += 1
    for kind, x0, y0, vx, vy, sc, rs, ph in STICK:
        x = (x0 + vx * t) % (W + 400) - 200
        y = y0 + vy * t + 18 * math.sin(t * 2 + ph)
        spr = pomegranate() if kind == "pom" else flag(t, phase=ph)
        k = 0.75 if kind == "flag" else 0.95
        spr = spr.resize((int(spr.width * sc * k), int(spr.height * sc * k)), Image.BILINEAR)
        spr = spr.rotate(rs * math.sin(t * 0.8 + ph) * 0.5 + (rs if kind == "pom" else 0), Image.BILINEAR, expand=True)
        fr.alpha_composite(spr, (int(x - spr.width / 2), int(y - spr.height / 2)))
    return fr


def title_bg(t, dur):
    fr = market_layer(t)
    # как в «ОБСИДИАН»: огромные слова на тёмном фоне, внутри букв — цветной рынок
    out = Image.new("RGBA", (W, H), OBSIDIAN + (255,))
    p = ease_out((t - 0.1) / 0.5)
    sq = int(round(lerp(112, 100, p)))
    big, small = title_masks(sq)
    out.paste(fr, (0, 0), big.point(lambda v: int(v * clamp(p * 1.5))))
    q = ease_out((t - 0.55) / 0.45)
    if q > 0:
        out.paste(fr, (0, 0), small.point(lambda v: int(v * q)))
    shine(out, (t - 1.7) / 1.1)
    return out


clip(4.0, 8.0, title_bg, "zoom", 0.3)
hit(4.55, 16)
hit(5.05, 8)
TITLE_IDX = len(CL) - 1

# ---- 2 · Ереван — см. космическую вставку ниже; клип 8–11 нужен только как «предыдущий» для перехода в ряды
clip(8.0, 11.0, lambda t, dur: space.draw(space.LENGTH - 1 / FPS, space.LENGTH), "whip", 0.3)
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
HIST_PREV = len(CL) - 1
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


# ---- 5–6 · История 1970 → 2026 (вставка на своей шкале H0, см. vtime)
H0 = 3000.0
ERA = 3.0
ERAS = [  # год, суффикс, строка 1, строка 2, плашка, фото, стиль
    (1970, "‑е", "слово «вернисаж»", "приходит в Ереван", "так называют показы картин",
     ["CCascade in 1970s.jpg", "COld Cascade 01.jpg"], "bw"),
    (1980, "‑е", "художники выставляют", "картины на улице", "сквер Сарьяна", ["CArmenia, Yerevan (2166087660).jpg"], "sepia"),
    (1988, "", "после землетрясения", "ремесло кормит мастеров", "стойкость", ["CRuins in Spitak after the 1988 earthquake.jpg"], "bw"),
    (1991, "", "независимость", "Армении", "рынок растёт", ["CRally for the Armenian Referendum for Independence 1991.jpg",
                                                        "CErevan - Vernissage 02.JPG"], "faded"),
    (2000, "‑е", "ряды у площади", "Республики", "ул. Арама и Бузанда", ["CErevan - Vernissage 01.JPG", "CYerevan Vernissage view.jpg"], "faded"),
    (2016, "", "реконструкция", "новые павильоны", "более 3 гектаров", ["CYerevan Vernissage by ArmAg (1).jpg"], "color"),
    (2023, "", "рекорд туризма", "2,3 млн гостей Армении", "очереди у прилавков", ["R543", "Y070"], "color"),
    (2026, "", "сегодня", "гости со всего мира", "~1000 продавцов", ["R290", "Y058"], "vivid"),
]
HIST_LEN = ERA * len(ERAS)


@lru_cache(maxsize=None)
def polaroid_style(key, w, angle, style):
    from PIL import ImageEnhance
    im = ImageOps.fit(raw(key), (w, int(w * 0.75)), Image.LANCZOS)
    if style == "bw":
        im = ImageEnhance.Contrast(ImageOps.grayscale(im).convert("RGB")).enhance(1.15)
    elif style == "sepia":
        im = ImageOps.colorize(ImageOps.grayscale(im), (55, 38, 22), (250, 232, 200))
    elif style == "faded":
        im = Image.blend(ImageEnhance.Color(im).enhance(0.55), Image.new("RGB", im.size, (240, 220, 190)), 0.12)
    elif style == "vivid":
        im = ImageEnhance.Color(im).enhance(1.25)
    m = int(w * 0.05)
    card = Image.new("RGBA", (w + 2 * m, im.height + m + int(w * 0.16)), (252, 250, 245, 255))
    card.paste(im, (m, m))
    sh = Image.new("RGBA", (card.width + 100, card.height + 100), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle((50, 64, card.width + 50, card.height + 64), fill=(0, 0, 0, 120))
    sh = sh.filter(ImageFilter.GaussianBlur(20))
    sh.alpha_composite(card, (50, 50))
    return sh.rotate(angle, Image.BICUBIC, expand=True)


def era_layout(n):
    return [(1400, 520, 720, -3)] if n == 1 else [(1250, 400, 560, -5), (1560, 640, 560, 6)]


for e, (*_, photos, style) in enumerate(ERAS):
    for i in range(len(photos)):
        hit(H0 + e * ERA + 0.35 + i * 0.35 + 0.2, 12)


def history2(t, dur):
    fr = Image.new("RGBA", (W, H), CREAM + (255,))
    d = ImageDraw.Draw(fr)
    for i in range(0, W + H, 90):
        d.line((i, 0, i - H, H), fill=(238, 228, 212, 255), width=2)
    e = min(len(ERAS) - 1, int(t // ERA))
    lt = t - e * ERA
    if e > 0 and lt < 0.35:  # предыдущая эпоха уезжает влево
        pe = ERAS[e - 1]
        for (x, y, w, ang), key in zip(era_layout(len(pe[5])), pe[5]):
            paste(fr, polaroid_style(key, w, ang, pe[6]), x - ease_in(lt / 0.35) * 1500, y, 1.0, "mm")
    era = ERAS[e]
    for i, ((x, y, w, ang), key) in enumerate(zip(era_layout(len(era[5])), era[5])):
        land(fr, polaroid_style(key, w, ang, era[6]), x, y, lt, 0.35 + i * 0.35)
    return fr


TL_XS = [130 + i * 118 for i in range(len(ERAS))]


def history2_counter(fr, t):
    lt = t - H0
    e = min(len(ERAS) - 1, int(lt // ERA))
    y0 = ERAS[e - 1][0] if e else 1960
    y1, suf = ERAS[e][0], ERAS[e][1]
    pp = (lt - e * ERA) / 0.45
    v = int(round(lerp(y0, y1, ease_out(pp))))
    s = text_sprite(f"{v}{suf if v == y1 else ''}", 200, "Black", POM, shadow=False)
    sc = 1.0 + (0.1 * (1 - ease_out((pp - 1) / 0.3)) if 1 <= pp < 1.3 else 0)
    paste(fr, scaled(s, sc), 110, 250, clamp(lt / 0.2) * clamp((H0 + HIST_LEN - t) / 0.2), "lm")
    years = [x[0] for x in ERAS]
    xs = TL_XS
    dr = ImageDraw.Draw(fr)
    dr.line((100, 1000, xs[-1] + 30, 1000), fill=TUFF + (255,), width=4)
    pos = float(np.interp(v, years, xs))
    dr.line((100, 1000, pos, 1000), fill=POM + (255,), width=9)
    for x, yv in zip(xs, years):
        on = abs(pos - x) < 3
        r = 14 if on else 7
        dr.ellipse((x - r, 1000 - r, x + r, 1000 + r), fill=(POM if on else TUFF) + (255,))
        paste(fr, text_sprite(str(yv), 28 if on else 23, "Bold" if on else "Medium", POM if on else (130, 100, 85), shadow=False),
              x, 962, 1.0, "mb")


clip(H0, H0 + HIST_LEN, history2, "up", 0.4, prev=HIST_PREV)
over(H0, H0 + HIST_LEN, history2_counter)
for e, (yr, suf, l1, l2, bar, photos, style) in enumerate(ERAS):
    a0, a1 = H0 + e * ERA, H0 + (e + 1) * ERA - 0.05
    T_words(a0 + 0.45, a1, l1, 120, 420, 58, OBSIDIAN, "Bold")
    T_words(a0 + 0.65, a1, l2, 120, 495, 58, OBSIDIAN, "Bold")
    T_bar(a0 + 1.0, a1, bar, 120, 630, 52, POM, WHITE)

# ---- 6b · Годы взлетают, кружатся и превращаются в знак вечности (аревахач)
SYM0 = 4000.0
SYM_LEN = 6.5  # кратно доле — склейки после знака остаются в сетке
SC, SR = (957.0, 548.0), 322.0  # центр и радиус золотого знака в кадре (по картинке заказчика)
ARM_R = SR * 0.84


@lru_cache(maxsize=1)
def gold_symbol():
    """Золотой знак заказчика без его серого фона: фон вырезан по цвету, плетёный край сохранён."""
    path = os.path.join(A.space, "arevakhach_gold.jpg")
    im = Image.open(path).convert("RGB")
    im = ImageOps.fit(im, (W, H), Image.LANCZOS).filter(ImageFilter.UnsharpMask(2, 80, 2))
    a = np.asarray(im, np.float32)
    bg = np.median(a[:60, :60].reshape(-1, 3), 0)
    diff = np.abs(a - bg).max(2)
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.hypot(xx - SC[0], yy - SC[1])
    alpha = np.where(r < SR * 0.93, 1.0, np.clip((diff - 6) / 22, 0, 1)) * (r < SR * 1.05)
    alpha = np.asarray(Image.fromarray((alpha * 255).astype(np.uint8), "L").filter(ImageFilter.GaussianBlur(0.8)), np.uint8)
    out = im.convert("RGBA")
    out.putalpha(Image.fromarray(alpha, "L"))
    return out


@lru_cache(maxsize=1)
def hist_end_frame():
    return history2(HIST_LEN - 0.01, HIST_LEN)


@lru_cache(maxsize=1)
def sym_grid():
    pad = int(SR * 1.3)
    yy, xx = np.mgrid[-pad:pad, -pad:pad].astype(np.float32)
    return pad, xx, yy


def symbol_mask(phi, reveal, ring):
    """Маска знака: 8 серповидных ветвей + центр + кольцо. reveal[k] ∈ [0,1] — насколько выросла ветвь k."""
    pad, xx, yy = sym_grid()
    r = np.hypot(xx, yy)
    R = ARM_R
    acc = np.zeros_like(xx)
    for k in range(8):
        if reveal[k] <= 0:
            continue
        a = math.radians(k * 45) + phi
        c1 = (0.5 * R * math.cos(a), 0.5 * R * math.sin(a))
        c2 = (0.5 * R * math.cos(a + math.radians(30)), 0.5 * R * math.sin(a + math.radians(30)))
        d1 = np.hypot(xx - c1[0], yy - c1[1])
        d2 = np.hypot(xx - c2[0], yy - c2[1])
        m = np.clip((0.5 * R - d1) / 1.5, 0, 1) * np.clip((d2 - 0.53 * R) / 1.5, 0, 1)
        m *= np.clip((R * reveal[k] - r) / 3, 0, 1)
        acc = np.maximum(acc, m)
    acc = np.maximum(acc, np.clip((0.07 * R - r) / 1.5, 0, 1) * (1 if sum(reveal) > 0 else 0))
    if ring > 0:
        ang = (np.degrees(np.arctan2(yy, xx)) + 360 + 90) % 360
        band = np.clip((r - SR * 0.9) / 1.5, 0, 1) * np.clip((SR * 0.98 - r) / 1.5, 0, 1)
        acc = np.maximum(acc, band * (ang <= ring * 360))
    m = Image.new("L", (W, H), 0)
    m.paste(Image.fromarray((acc * 255).astype(np.uint8), "L"), (int(SC[0] - pad), int(SC[1] - pad)))
    return m


def sym_phi(t):
    # вращение: разгон, кружение, торможение к финальному положению
    return -(0.6 * t + 1.6 * ease_in_out((t - 0.6) / 2.6) * math.pi * 0.9 + 0.8 * ease_out((t - 3.2) / 1.0))


def symbol_scene(t, dur):
    years = [e[0] for e in ERAS]
    darkk = ease_in_out((t - 0.35) / 0.7)
    night = Image.fromarray(night_sky().astype(np.uint8)).convert("RGBA")  # общий фон со сценой Арарата
    fr = Image.blend(Image.new("RGBA", (W, H), CREAM + (255,)), night, darkk)
    if t < 0.7:  # фото и шкала уходят
        h = hist_end_frame()
        o = 1 - ease_in(t / 0.6)
        if o > 0:
            fr.alpha_composite(with_alpha(h.transform((W, H), Image.AFFINE, (1, 0, 0, 0, 1, -int(ease_in(t / 0.6) * 140))), o))
        d = ImageDraw.Draw(fr)
        w = (TL_XS[-1] + 30 - 100) * (1 - ease_in_out(t / 0.5))
        if w > 1:
            d.line((100, 1000, 100 + w, 1000), fill=POM + (255,), width=9)
    phi = sym_phi(t)
    if t >= 2.3:  # ветви растут из центра, каждая — из своего года
        reveal = [ease_out((t - 2.3 - k * 0.16) / 0.45) for k in range(8)]
        ring = ease_in_out((t - 3.7) / 0.6)
        mask = symbol_mask(phi, reveal, ring)
        fr.paste(market_layer(t), (0, 0), mask)
    # годы: со шкалы → на круг → кружатся → растворяются в своей ветви
    for k, yv in enumerate(years):
        p = ease_in_out((t - 0.2 - k * 0.05) / 0.8)
        a = math.radians(k * 45) + phi
        cx, cy = SC[0] + SR * 1.05 * math.cos(a), SC[1] + SR * 1.05 * math.sin(a)
        x = lerp(TL_XS[k], cx, p)
        y = lerp(962 - 20, cy, p)
        gone = ease_in((t - 2.3 - k * 0.16) / 0.4)
        o = 1 - gone
        if o <= 0:
            continue
        col = POM if darkk < 0.5 else APRICOT
        size = int(lerp(28, 62, p) * (1 - 0.5 * gone))
        paste(fr, text_sprite(str(yv), max(10, size), "Black", col, shadow=darkk > 0.5), x, y, o, "mm")
    # цветной знак → золотой (как на картинке) и стоп‑кадр на 1 секунду
    g = ease_in_out((t - 4.3) / 0.8)
    if g > 0:
        fr.alpha_composite(with_alpha(gold_symbol(), g))
    return fr


clip(SYM0, SYM0 + SYM_LEN, symbol_scene, None)
for k in range(8):
    hit(SYM0 + 2.3 + k * 0.16 + 0.2, 6)
hit(SYM0 + 4.0, 14)

# ---- 6c · Знак → солнце над Араратом → гора ложится на расписной спил (R857) → отъезд
ARR0 = 4500.0
ARR_LEN = 6.5  # 13 долей
PH_B0 = (515.0, 317.0, 1150.0)        # кадр спила, на который ложится векторная гора: x0, y0, ширина
PH_FULL = (0.0, 180.0, 1920.0)        # весь спил с рукой продавца
SUN_POS, SUN_R = (840.0, 205.0), 74.0


def _poly(d, pts, fill):
    d.polygon([(x * 2, y * 2) for x, y in pts], fill=fill)


@lru_cache(maxsize=1)
def ararat_layers():
    """Векторные слои (рисуются в 2× и сглаживаются): дальний хребет, Арарат со снегом, холм с Хор Вирапом, поле."""
    WW, HH = W * 2, H * 2
    rng = np.random.default_rng(5)

    def layer():
        return Image.new("RGBA", (WW, HH), (0, 0, 0, 0))

    far = layer()
    df = ImageDraw.Draw(far)
    xs = np.linspace(-150, 2100, 60)
    ys = 700 + 40 * np.sin(xs / 210) + 18 * np.sin(xs / 57)
    _poly(df, [(-150, 1100)] + list(zip(xs, ys)) + [(2100, 1100)], (122, 111, 166, 235))

    # силуэт Арарата: опорные точки по картине на спиле, сглаженные сплайном
    key = [(-160, 760), (-75, 673), (200, 520), (330, 420), (417, 364), (470, 392), (560, 432), (700, 462),
           (793, 473), (950, 402), (1150, 300), (1260, 246), (1327, 230), (1400, 242), (1520, 252), (1678, 262),
           (1800, 334), (1920, 420), (2012, 506), (2100, 640)]
    ridge = []
    for k in range(len(key) - 1):
        p0, p1 = key[max(k - 1, 0)], key[k]
        p2, p3 = key[k + 1], key[min(k + 2, len(key) - 1)]
        for u in np.linspace(0, 1, 10, endpoint=False):
            ridge.append(tuple(0.5 * ((2 * np.array(p1)) + (-np.array(p0) + p2) * u
                                      + (2 * np.array(p0) - 5 * np.array(p1) + 4 * np.array(p2) - np.array(p3)) * u * u
                                      + (-np.array(p0) + 3 * np.array(p1) - 3 * np.array(p2) + p3) * u ** 3)))
    ridge.append(key[-1])
    ridge = [(x, y + 3 * rng.standard_normal()) for x, y in ridge]
    body = [(-160, 1000)] + ridge + [(2100, 1000)]
    m = Image.new("L", (WW, HH), 0)
    _poly(ImageDraw.Draw(m), body, 255)
    mA = np.asarray(m, np.float32) / 255
    g = np.linspace(0, 1, HH, dtype=np.float32)[:, None]
    rgb = np.dstack([np.repeat(lerp(128, 70, g), WW, 1), np.repeat(lerp(130, 72, g), WW, 1), np.repeat(lerp(200, 140, g), WW, 1)])
    # снег: выше рваной снеговой линии, с языками вниз по склонам
    xs = np.linspace(-160, 2100, 260)
    walk = np.convolve(np.cumsum(rng.standard_normal(len(xs))), np.ones(9) / 9, "same")
    walk = (walk - walk.mean()) / (walk.std() + 1e-9)
    tongues = sum(rng.uniform(25, 70) * np.exp(-((xs - c) / rng.uniform(12, 30)) ** 2) for c in rng.uniform(-100, 2050, 18))
    snow_y = 560 + 28 * walk + 18 * np.sin(xs / 140) + tongues
    sm = Image.new("L", (WW, HH), 0)
    _poly(ImageDraw.Draw(sm), [(-160, -10)] + list(zip(xs, snow_y)) + [(2100, -10)], 255)
    snowA = np.asarray(sm.filter(ImageFilter.GaussianBlur(3)), np.float32) / 255 * mA
    rgb = rgb * (1 - snowA[..., None]) + np.array([246, 247, 255], np.float32) * snowA[..., None]
    # мягкие тени на правых склонах (размытые маски) — объём без «блоков»
    sh = Image.new("L", (WW, HH), 0)
    dsh = ImageDraw.Draw(sh)
    _poly(dsh, [(417, 364), (470, 392), (560, 432), (700, 462), (793, 473), (700, 640), (520, 720), (440, 620)], 255)
    _poly(dsh, [(1327, 230), (1400, 242), (1520, 252), (1678, 262), (1800, 334), (1920, 420), (2012, 506), (2100, 640),
                (2100, 900), (1700, 820), (1460, 620), (1360, 420)], 255)
    shA = np.asarray(sh.filter(ImageFilter.GaussianBlur(70)), np.float32)[..., None] / 255 * mA[..., None]
    rgb = rgb * (1 - 0.32 * shA) + np.array([60, 62, 130], np.float32) * 0.32 * shA
    # дымка у подножия
    haze = np.clip((g - 0.62) / 0.3, 0, 1)[..., None]
    rgb = rgb * (1 - 0.35 * haze) + np.array([170, 160, 210], np.float32) * 0.35 * haze
    mtn = Image.fromarray(np.dstack([rgb, mA * 255]).astype(np.uint8), "RGBA")

    hill = layer()
    dh = ImageDraw.Draw(hill)
    hp_ = [(893, 1090), (980, 905), (1100, 795), (1144, 742), (1300, 706), (1500, 664), (1700, 642), (1979, 575), (2100, 592), (2100, 1090)]
    _poly(dh, hp_, (164, 82, 61, 255))
    _poly(dh, [(1144, 742), (1300, 706), (1500, 664), (1700, 642), (1979, 575), (2100, 592), (2100, 640), (1700, 690), (1300, 750), (1150, 790)], (196, 112, 84, 255))
    # Хор Вирап
    c = (43, 29, 26, 255)
    _poly(dh, [(1290, 708), (1290, 645), (1505, 645), (1505, 708)], c)
    _poly(dh, [(1372, 645), (1372, 596), (1416, 596), (1416, 645)], c)
    _poly(dh, [(1362, 598), (1394, 548), (1426, 598)], c)
    dh.line((1394 * 2, 548 * 2, 1394 * 2, 506 * 2), fill=c, width=8)
    dh.line((1381 * 2, 522 * 2, 1407 * 2, 522 * 2), fill=c, width=8)
    _poly(dh, [(1452, 645), (1474, 616), (1496, 645)], c)
    dh.line((1474 * 2, 616 * 2, 1474 * 2, 596 * 2), fill=c, width=6)

    field = layer()
    dfl = ImageDraw.Draw(field)
    _poly(dfl, [(-20, 965), (450, 950), (900, 940), (1000, 1090), (-20, 1090)], (110, 150, 62, 255))
    for cx, cy, rx, ry, colr in [(120, 860, 90, 210, (52, 92, 46)), (300, 900, 80, 170, (62, 104, 52)), (520, 990, 160, 110, (86, 128, 54)),
                                 (1250, 1010, 170, 120, (78, 124, 50)), (1520, 1000, 180, 120, (70, 116, 48)), (1800, 980, 190, 140, (66, 110, 46))]:
        dfl.ellipse(((cx - rx) * 2, (cy - ry) * 2, (cx + rx) * 2, (cy + ry) * 2), fill=colr + (255,))
    return [l.resize((W, H), Image.LANCZOS) for l in (far, mtn, hill, field)]


@lru_cache(maxsize=1)
def sun_disc():
    """Золотой знак, вырезанный кругом из картинки заказчика."""
    g = gold_symbol()
    r = int(SR * 1.05)
    return g.crop((int(SC[0] - r), int(SC[1] - r), int(SC[0] + r), int(SC[1] + r)))


def sky(k_sunset, k_day):
    y = np.linspace(0, 1, H, dtype=np.float32)[:, None]
    sunset = np.stack([lerp(58, 246, y ** 1.3), lerp(36, 152, y ** 1.3), lerp(92, 112, y ** 1.1)], -1)
    day = np.stack([lerp(70, 168, y), lerp(130, 206, y), lerp(214, 236, y)], -1)
    base = np.full((H, 1, 3), 37.0, np.float32)
    c = base * (1 - k_sunset) + (sunset * (1 - k_day) + day * k_day) * k_sunset
    return np.repeat(c, W, 1)


@lru_cache(maxsize=1)
def ararat_photo():
    return raw("R857")


def photo_box(x0, y0, w):
    h = w * H / W
    return ararat_photo().transform((W, H), Image.EXTENT, (x0, y0, x0 + w, y0 + h), Image.BILINEAR).convert("RGBA")


LOGO_S = 2.65                       # рисунок заказчика без искажений, единый масштаб, целиком в кадре
# середина между вершинами логотипа — на середину между вершинами Арарата на спиле
LOGO_OX, LOGO_OY = 872 - (181 + 445) / 2 * LOGO_S, 297 - (125 + 68) / 2 * LOGO_S
LINE_COLOR = {"white": (255, 255, 255), "gold": (246, 196, 92)}[os.environ.get("ARARAT_COLOR", "gold")]
GLOW_COLOR = {"white": (255, 214, 160), "gold": (255, 160, 60)}[os.environ.get("ARARAT_COLOR", "gold")]


@lru_cache(maxsize=1)
def ararat_logo_mask():
    """Контур Арарата — точно рисунок заказчика (в его пропорциях), линии утончены."""
    lg = Image.open(os.path.join(A.space, "ararat_logo.png")).convert("L")
    w, h = int(lg.width * LOGO_S), int(lg.height * LOGO_S)
    lg = lg.resize((w, h), Image.LANCZOS).point(lambda v: 0 if v < 60 else (255 if v > 160 else int((v - 60) * 255 / 100)))
    lg = lg.filter(ImageFilter.MinFilter(13)).filter(ImageFilter.GaussianBlur(1.0))  # тоньше, края мягкие
    m = Image.new("L", (W, H), 0)
    m.paste(lg, (int(LOGO_OX), int(LOGO_OY)))
    return m


@lru_cache(maxsize=1)
def khor_virap_mask():
    """Хор Вирап той же формы — тонким контуром, холм — тонкой линией."""
    S2 = 2
    fill = Image.new("L", (W * S2, H * S2), 0)
    d = ImageDraw.Draw(fill)
    for poly in ([(1290, 708), (1290, 645), (1505, 645), (1505, 708)], [(1372, 645), (1372, 596), (1416, 596), (1416, 645)],
                 [(1362, 598), (1394, 548), (1426, 598)], [(1452, 645), (1474, 616), (1496, 645)]):
        d.polygon([(x * S2, y * S2) for x, y in poly], fill=255)
    outline = Image.fromarray((np.asarray(fill.filter(ImageFilter.MaxFilter(9)), np.int16)
                               - np.asarray(fill, np.int16)).clip(0, 255).astype(np.uint8), "L")
    d = ImageDraw.Draw(outline)
    hill = [(1070, 850), (1144, 742), (1300, 706), (1500, 664), (1700, 642), (1979, 575), (2100, 592)]
    d.line([(x * S2, y * S2) for x, y in hill], fill=255, width=9, joint="curve")
    d.line((1394 * S2, 548 * S2, 1394 * S2, 506 * S2), fill=255, width=6)
    d.line((1381 * S2, 522 * S2, 1407 * S2, 522 * S2), fill=255, width=6)
    d.line((1474 * S2, 616 * S2, 1474 * S2, 596 * S2), fill=255, width=5)
    return outline.resize((W, H), Image.LANCZOS)


@lru_cache(maxsize=1)
def night_sky():
    """Тёмное ночное небо со звёздами (цвет низа совпадает с фоном знака)."""
    y = np.linspace(0, 1, H, dtype=np.float32)[:, None]
    c = np.stack([lerp(14, 40, y), lerp(18, 30, y), lerp(42, 48, y)], -1).repeat(W, 1)
    rng = np.random.default_rng(21)
    n = 700
    xs, ys = rng.integers(0, W, n), (rng.random(n) ** 1.6 * H * 0.75).astype(int)
    br = rng.random(n) ** 3 * 200 + 40
    for x, yy, b in zip(xs, ys, br):
        c[yy, x] = np.minimum(255, c[yy, x] + b)
    img = Image.fromarray(c.astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6))
    return np.asarray(img, np.float32)


def glow_lines(mask, strength):
    a = np.asarray(mask, np.float32)[..., None] / 255
    g1 = np.asarray(mask.filter(ImageFilter.GaussianBlur(5)), np.float32)[..., None] / 255
    g2 = np.asarray(mask.filter(ImageFilter.GaussianBlur(20)), np.float32)[..., None] / 255
    return (a * np.array(LINE_COLOR) + g1 * np.array(GLOW_COLOR) * 0.9 + g2 * np.array(GLOW_COLOR) * 0.7) * strength


ARR_PIVOT = (872.0, 600.0)  # центр роста — между вершинами, у подножия
Z_SMALL, Z_MAX = 0.32, 1.38


def ararat_zoom(t):
    """Масштаб горы: растёт из маленькой до полного размера, затем — «до предела»."""
    return Z_SMALL * (1.0 / Z_SMALL) ** ease_out((t - 0.9) / 1.4) * (Z_MAX ** ease_in_out((t - 2.3) / 0.8))


def scale_about(img, z, mode="L"):
    """Масштаб изображения на весь кадр вокруг ARR_PIVOT."""
    px, py = ARR_PIVOT
    return img.transform((W, H), Image.AFFINE, (1 / z, 0, px - px / z, 0, 1 / z, py - py / z), Image.BILINEAR)


def photo_at_zoom(z):
    """Кадр спила, совпадающий с вектором при масштабе z (z=1 — исходное совмещение PH_B0)."""
    x0b, y0b, wb = PH_B0
    k = wb / W
    pxp, pyp = x0b + ARR_PIVOT[0] * k, y0b + ARR_PIVOT[1] * k
    w = wb / z
    return pxp - ARR_PIVOT[0] * w / W, pyp - ARR_PIVOT[1] * w / W, w


def ararat_scene(t, dur):
    bg = night_sky()  # тот же фон, что и у знака вечности — без скачка цвета
    fr = Image.fromarray(bg.astype(np.uint8)).convert("RGBA")
    # 1) знак уменьшается и поднимается над седловиной — становится солнцем; гаснет, когда гора растёт до предела
    p = ease_in_out(t / 1.4)
    r = lerp(SR * 1.02, 92.0, p)
    cx, cy = lerp(SC[0], 860.0, p), lerp(SC[1], 150.0, p)
    sun_o = 1 - ease_in_out((t - 2.3) / 0.7)
    if sun_o > 0:
        glow = Image.new("L", (W, H), 0)
        gr = r * 2.2
        ImageDraw.Draw(glow).ellipse((cx - gr, cy - gr, cx + gr, cy + gr), fill=int(140 * p * sun_o))
        glow = glow.filter(ImageFilter.GaussianBlur(r * 0.8))
        fr.alpha_composite(Image.merge("RGBA", (Image.new("L", (W, H), 255), Image.new("L", (W, H), 205),
                                                 Image.new("L", (W, H), 140), glow)))
        disc = sun_disc().resize((max(2, int(2 * r)), max(2, int(2 * r))), Image.LANCZOS).rotate(-t * 40, Image.BICUBIC)
        paste(fr, disc, cx, cy, sun_o, "mm")
    # 2) Арарат появляется маленьким и растёт до предела (светящиеся золотые линии + Хор Вирап)
    z = ararat_zoom(t)
    appear = ease_out((t - 0.9) / 0.5)
    lines_o = appear * (1 - ease_in_out((t - 3.3) / 0.5))
    if lines_o > 0:
        hk = ease_out((t - 1.7) / 0.6)
        m = np.asarray(ararat_logo_mask(), np.float32)
        if hk > 0:
            x = np.arange(W, dtype=np.float32)[None, :]
            m = np.maximum(m, np.asarray(khor_virap_mask(), np.float32) * np.clip((lerp(1040, 2150, hk) - x) / 60, 0, 1))
        mz = scale_about(Image.fromarray(m.astype(np.uint8), "L"), z)
        add = glow_lines(mz, lines_o)
        a = np.asarray(fr.convert("RGB"), np.float32) + add
        fr = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).convert("RGBA")
    # 3) гора превращается в картину: картина проступает изнутри горы и расходится на весь кадр
    k_x = ease_in_out((t - 3.0) / 0.8)
    if k_x > 0:
        # 4) затем уменьшается уже картина — камера отъезжает, видно спил в руке продавца
        pb = ease_in_out((t - 3.9) / 1.9)
        x1, y1, w1 = photo_at_zoom(Z_MAX)
        x0 = lerp(x1, PH_FULL[0], pb)
        y0 = lerp(y1, PH_FULL[1], pb)
        w = w1 * (PH_FULL[2] / w1) ** pb
        ph = np.asarray(photo_box(x0, y0, w).convert("RGB"), np.float32)
        if k_x < 1:
            yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
            rad = np.hypot(xx - ARR_PIVOT[0], (yy - ARR_PIVOT[1] + 260) * 1.3)
            front = k_x * 1900
            mask = np.clip((front - rad) / 220, 0, 1)[..., None]
            cur = np.asarray(fr.convert("RGB"), np.float32)
            out = cur * (1 - mask) + ph * mask
            out = out + np.clip(cur - bg, 0, None) * mask * lines_o * 0.6  # золотые линии видны поверх картины, пока гаснут
            fr = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).convert("RGBA")
        else:
            fr = Image.fromarray(ph.astype(np.uint8)).convert("RGBA")
    return fr


clip(ARR0, ARR0 + ARR_LEN, ararat_scene, None)

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
    ("05", "ОБСИДИАН", "вулканическое стекло", "C2017-Obsidian-Armenia-Vtorov.jpg", OBSIDIAN,
     [("C2017-Obsidian-Armenia-Vtorov.jpg", "pan_r", 1.5), ("R867", "push", 1.5), ("R708", "pull", 1.5)]),
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
            clip(t, t + dur, shot(k, mv, sh=0.6, shine_at=0.2 if k in ("R867", "R708") else None),
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

# ---- 2 · Из космоса (вставка): Солнечная система → Земля → Армения → Ереван → Вернисаж
# Сцена живёт на собственной шкале 1000…1014 с; frame_global() вклеивает её после интро.
SP0 = 1000.0
clip(SP0, SP0 + space.LENGTH, space.draw, "zoom", 0.35, prev=TITLE_IDX)
M = space.MAP_SHIFT  # тайминги карты — на старой шкале сцены
T_slam(SP0 + 9.3 - M, SP0 + 11.1 - M, "АРМЕНИЯ", W // 2, 880, 120, CREAM, amp=14)
T_words(SP0 + 9.7 - M, SP0 + 11.1 - M, "Հայաստան", W // 2, 990, 52, APRICOT, "SemiBold", "m")
T_slam(SP0 + 11.6 - M, SP0 + 12.95 - M, "ЕРЕВАН", W // 2, 880, 120, CREAM)
over(SP0 + 11.9 - M, SP0 + 12.95 - M, lambda fr, t: paste(fr, text_sprite("40.18° N · 44.51° E"[:int((t - SP0 - 11.9 + M) * 40)] or " ", 40, "Medium", APRICOT),
                                                         W // 2, 985, clamp((SP0 + 12.95 - M - t) / 0.2), "mm"))
T_chip(SP0 + 13.3 - M, SP0 + space.LENGTH, "ВЕРНИСАЖ", W // 2, H // 2 + 90, 58)
T_words(SP0 + 13.5 - M, SP0 + space.LENGTH, "ул. Арама · ул. Бузанда", W // 2, H // 2 + 175, 40, CREAM, "SemiBold", "m")

# Монтаж: (начало на шкале сцен, длительность)
SEGMENTS = [(0.0, 8.0), (SP0, space.LENGTH), (11.0, 19.0), (H0, HIST_LEN), (SYM0, SYM_LEN), (ARR0, ARR_LEN), (42.0, 70.0)]
DURATION = sum(d for _, d in SEGMENTS)


TAIL_SPEED = 1.0  # ускорение всего после интро (подгонка склеек под темп трека), задаётся --tail-speed
INTRO_LEN = SEGMENTS[0][1]


def out_duration():
    return INTRO_LEN + (DURATION - INTRO_LEN) / TAIL_SPEED


def vtime(T):
    """Глобальное время ролика → время на шкале сцен."""
    if T > INTRO_LEN:
        T = INTRO_LEN + (T - INTRO_LEN) * TAIL_SPEED
    for start, length in SEGMENTS:
        if T < length:
            return start + T
        T -= length
    s0, l0 = SEGMENTS[-1]
    return s0 + l0 - 1e-3


# ================================================================ compositing
def background(t):
    idx = next((i for i, c in enumerate(CL) if c[0] <= t < c[1]), len(CL) - 1)
    t0, t1, fn, tr, td, prev = CL[idx]
    fr = fn(t - t0, t1 - t0).convert("RGBA")
    if tr and t - t0 < td and idx > 0:
        p0, p1, pfn = CL[idx - 1 if prev is None else prev][:3]
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


def frame_at(T):
    t = vtime(T)
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
    arr = np.asarray(img, np.float32) * f["vig"] + f["grain"][int(T * FPS) % 6]
    return np.clip(arr, 0, 255).astype(np.uint8)


API = {}


def init_worker(args):
    global A, TAIL_SPEED
    A = args
    TAIL_SPEED = args.tail_speed
    API.update(text_sprite=text_sprite, paste=paste, ease_back=ease_back)
    space.setup(A.space, API)


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
    ap.add_argument("--space", required=True, help="папка с ассетами космической сцены (space_assets.py)")
    ap.add_argument("-o", "--out", default="vernissage.mp4")
    ap.add_argument("--music")
    ap.add_argument("--preview")
    ap.add_argument("--range")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--tail-speed", type=float, default=1.0,
                    help="ускорить всё после интро (1.25 — склейки на 150 BPM вместо 120)")
    A = ap.parse_args()
    init_worker(A)

    if A.preview:
        for s in A.preview.split(","):
            t = float(s)
            Image.fromarray(frame_at(t)).save(f"{os.path.splitext(A.out)[0]}_{t:06.2f}.png")
        return

    start, end = (map(float, A.range.split(","))) if A.range else (0.0, out_duration())
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
