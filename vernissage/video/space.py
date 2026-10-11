"""Сцена «из космоса»: Солнечная система → Земля → неоновая Армения (вместе с Арцахом) → Ереван → Вернисаж.

Планеты — текстурированные сферы (трассировка лучей в numpy) под перспективной
камерой, летящей по сплайну мимо Сатурна, Юпитера и Марса к Земле. Затем —
бесшовный переход с глобуса на спутниковую мозаику (Sentinel‑2) и зум до улицы.

Ассеты готовит space_assets.py (текстуры Solar System Scope CC BY 4.0,
EOxCloudless 2016 CC BY 4.0, Copernicus Sentinel‑2 2025, границы Natural Earth:
Армения + Нагорный Карабах в контуре 1994–2020 гг. из Natural Earth v4.1.0).
"""
import glob
import json
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

W, H = 1920, 1080
F = (W / 2) / math.tan(math.radians(25))  # горизонтальный FOV 50°
CX, CY = W / 2, H / 2
LENGTH = 14.0

CREAM = (245, 237, 224)
POM = (158, 27, 50)
APRICOT = (244, 162, 89)

DIR = None
API = None  # функции из render.py: text_sprite, paste, ease_*, clamp, lerp


def setup(path, api):
    global DIR, API
    DIR, API = path, api


# ================================================================ helpers
def smooth(p):
    p = min(1.0, max(0.0, p))
    return p * p * (3 - 2 * p)


def eio(p):
    p = min(1.0, max(0.0, p))
    return 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2


_T = {}


def tex(name, mode="RGB"):
    key = (name, mode)
    if key not in _T:
        _T[key] = np.asarray(Image.open(os.path.join(DIR, "tex", name)).convert(mode))
    return _T[key]


def sample(T, u, v):
    """Билинейная выборка из равнопромежуточной текстуры (u по кругу)."""
    h, w = T.shape[:2]
    x = (u % 1.0) * w - 0.5
    y = np.clip(v, 0, 1) * h - 0.5
    x0 = np.floor(x).astype(np.int32)
    y0 = np.floor(y).astype(np.int32)
    fx = (x - x0)[:, None].astype(np.float32)
    fy = (y - y0)[:, None].astype(np.float32)
    xa, xb = x0 % w, (x0 + 1) % w
    ya, yb = np.clip(y0, 0, h - 1), np.clip(y0 + 1, 0, h - 1)
    t = T if T.ndim == 3 else T[..., None]
    a = t[ya, xa].astype(np.float32)
    b = t[ya, xb].astype(np.float32)
    c = t[yb, xa].astype(np.float32)
    d = t[yb, xb].astype(np.float32)
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def roty(a, tilt=0.0):
    """Матрица мир→тело: вращение вокруг оси Y на a, наклон оси на tilt (вокруг X)."""
    ca, sa = math.cos(a), math.sin(a)
    ry = np.array([[ca, 0, sa], [0, 1, 0], [-sa, 0, ca]])  # тело→мир
    ct, st = math.cos(tilt), math.sin(tilt)
    rx = np.array([[1, 0, 0], [0, ct, -st], [0, st, ct]])
    return (rx @ ry).T  # мир→тело


def body_vec(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.stack([np.cos(la) * np.sin(lo), np.sin(la), np.cos(la) * np.cos(lo)], -1)


class Cam:
    def __init__(self, pos, target):
        self.p = np.asarray(pos, float)
        z = np.asarray(target, float) - self.p
        z /= np.linalg.norm(z)
        x = np.cross([0.0, 1.0, 0.0], z)
        x /= np.linalg.norm(x)
        self.x, self.y, self.z = x, np.cross(z, x), z

    def to_cam(self, P):
        d = np.asarray(P, float) - self.p
        return np.stack([d @ self.x, d @ self.y, d @ self.z], -1)

    def proj(self, P):
        c = self.to_cam(P)
        return CX + F * c[..., 0] / c[..., 2], CY - F * c[..., 1] / c[..., 2], c[..., 2]


# ================================================================ world
ORBITS = {  # имя: (радиус орбиты, угол°, радиус планеты, текстура, наклон оси°)
    "Меркурий": (2.0, 150, 0.10, "2k_mercury.jpg", 0),
    "Венера": (2.8, 205, 0.17, "2k_venus_atmosphere.jpg", 0),
    "Земля": (3.8, -60, 0.19, "8k_earth_daymap.jpg", 0),
    "Марс": (4.9, -55, 0.13, "2k_mars.jpg", 0),
    "Юпитер": (7.2, -47, 0.55, "8k_jupiter.jpg", 0),
    "Сатурн": (9.6, -30, 0.46, "8k_saturn.jpg", 22),
    "Уран": (12.0, 120, 0.30, "2k_uranus.jpg", 0),
    "Нептун": (14.2, 215, 0.29, "2k_neptune.jpg", 0),
}


def ppos(name):
    r, a, *_ = ORBITS[name]
    a = math.radians(a)
    return np.array([r * math.cos(a), 0.0, r * math.sin(a)])


EARTH = ppos("Земля")
ER = ORBITS["Земля"][2]
ARM = (40.18, 44.51)  # Ереван — точка, которую камера ставит в центр
LIGHT = np.array([-0.55, 0.50, -0.67])
LIGHT /= np.linalg.norm(LIGHT)

# финальное направление камеры на Землю: на 40° над горизонтом, со стороны пролёта
# заходим к Земле под углом 65° к линии «Солнце — Земля», чтобы Солнце ушло из кадра
_a = math.radians(ORBITS["Земля"][1] + 65)
_h = np.array([math.cos(_a), 0.0, math.sin(_a)])
_h /= np.linalg.norm(_h)
DIRV = np.array([math.cos(math.radians(ARM[0])) * _h[0], math.sin(math.radians(ARM[0])), math.cos(math.radians(ARM[0])) * _h[2]])
ALPHA_END = math.atan2(_h[0], _h[2]) - math.radians(ARM[1])
D_START, D_END = 1.7, 0.463

KEYS = [  # (время, позиция камеры)
    (0.0, (1.0, 25.0, -36.0)),
    (1.0, (2.5, 21.0, -31.0)),
    (2.4, (9.8, 2.3, -11.0)),
    (3.5, (6.4, 0.95, -7.6)),
    (4.6, (3.75, 0.55, -5.1)),
    (6.0, tuple(EARTH + DIRV * D_START)),
]


def catmull(t):
    ts = [k[0] for k in KEYS]
    ps = [np.array(k[1]) for k in KEYS]
    i = max(0, min(len(ts) - 2, int(np.searchsorted(ts, t, "right") - 1)))
    u = (t - ts[i]) / (ts[i + 1] - ts[i])
    p0, p1, p2, p3 = ps[max(i - 1, 0)], ps[i], ps[i + 1], ps[min(i + 2, len(ps) - 1)]
    return 0.5 * ((2 * p1) + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u * u + (-p0 + 3 * p1 - 3 * p2 + p3) * u ** 3)


def earth_dist(t):
    s = eio((t - 6.0) / 2.5) * 0.85 + min(1, max(0, (t - 6.0) / 2.5)) * 0.15
    return D_START * (D_END / D_START) ** s


def camera(t):
    if t < 6.0:
        pos = catmull(t)
        k = smooth((t - 0.9) / 2.3)
        target = np.zeros(3) * (1 - k) + EARTH * k
    else:
        pos = EARTH + DIRV * earth_dist(t)
        target = EARTH
    return Cam(pos, target)


def earth_rot(t):
    spin = math.radians(40) * (1 - smooth((t - 3.0) / 5.5))
    return roty(ALPHA_END - spin)


# ================================================================ rendering
def stars(cam):
    ys, xs = np.mgrid[0:H // 2, 0:W // 2].astype(np.float32)
    dx = (xs * 2 - CX) / F
    dy = -(ys * 2 - CY) / F
    d = dx[..., None] * cam.x + dy[..., None] * cam.y + cam.z
    d /= np.linalg.norm(d, axis=-1, keepdims=True)
    lon = np.arctan2(d[..., 0], d[..., 2])
    lat = np.arcsin(np.clip(d[..., 1], -1, 1))
    c = sample(tex("8k_stars_milky_way.jpg"), (lon / (2 * np.pi) + 0.5).ravel(), (0.5 - lat / np.pi).ravel())
    c = (np.clip(c / 255, 0, 1) ** 1.5 * 255 * 1.25).reshape(H // 2, W // 2, 3)
    return np.asarray(Image.fromarray(np.clip(c, 0, 255).astype(np.uint8)).resize((W, H), Image.BICUBIC), np.float32)


def draw_sphere(canvas, cam, center, r, texname, rot, emissive=False, earth=False, t=0.0, ring=False):
    C = cam.to_cam(center)
    dist = float(np.linalg.norm(C))
    if C[2] <= r * 1.02 or dist <= r * 1.001:
        return None
    sx, sy = CX + F * C[0] / C[2], CY - F * C[1] / C[2]
    Rp = F * r / math.sqrt(max(dist * dist - r * r, 1e-9))
    ext = Rp * (2.4 if ring else (1.45 if earth else 1.3)) + 3
    x0, x1 = int(max(0, sx - ext)), int(min(W, sx + ext + 1))
    y0, y1 = int(max(0, sy - ext)), int(min(H, sy + ext + 1))
    if x1 <= x0 or y1 <= y0:
        return None
    ys, xs = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    d = np.stack([(xs - CX) / F, -(ys - CY) / F, np.ones_like(xs)], -1)
    d /= np.linalg.norm(d, axis=-1, keepdims=True)
    b = d @ C
    cosang = np.clip(b / dist, -1, 1)
    theta = np.arccos(cosang)
    theta_s = math.asin(min(1.0, r / dist))
    alpha = np.clip((theta_s - theta) * F + 0.5, 0, 1)
    disc = np.maximum(b * b - (dist * dist - r * r), 0)
    tt = b - np.sqrt(disc)
    reg = canvas[y0:y1, x0:x1]

    ring_front = None
    if ring:  # кольца Сатурна: пересечение с плоскостью экватора
        n_w = rot.T @ np.array([0.0, 1.0, 0.0])
        n_c = np.array([n_w @ cam.x, n_w @ cam.y, n_w @ cam.z])
        dn = d @ n_c
        tr = (C @ n_c) / np.where(np.abs(dn) < 1e-6, 1e-6, dn)
        P = d * tr[..., None]
        rho = np.linalg.norm(P - C, axis=-1) / r
        on = (tr > 0) & (rho > 1.24) & (rho < 2.27)
        if on.any():
            rt = tex("8k_saturn_ring_alpha.png", "RGBA")
            rc = sample(rt, ((rho[on] - 1.24) / 1.03) * 0.999, np.full(on.sum(), 0.5))
            col = rc[:, :3] * 0.95
            a = rc[:, 3] / 255 * 0.9
            behind = on & ((alpha < 0.5) | (tr > tt))
            front = on & ~behind
            for mask in (behind,):
                sel = mask[on]
                reg[mask] = reg[mask] * (1 - a[sel, None]) + col[sel] * a[sel, None]
            ring_front = (front, col[front[on]], a[front[on]])

    m = alpha > 0
    if m.any():
        dm = d[m]
        P = dm * tt[m, None]
        n = (P - C) / r
        nw = n[:, :1] * cam.x + n[:, 1:2] * cam.y + n[:, 2:3] * cam.z
        bv = nw @ rot.T
        lon = np.arctan2(bv[:, 0], bv[:, 2])
        lat = np.arcsin(np.clip(bv[:, 1], -1, 1))
        u = lon / (2 * np.pi) + 0.5
        v = 0.5 - lat / np.pi
        col = sample(tex(texname), u, v)
        if earth:
            cl = sample(tex("8k_earth_clouds.jpg", "L"), u + 0.003 * t, v)[:, 0] / 255
            # над Арменией облака раздвигаются — чтобы её было видно
            arm = body_vec(*ARM)
            cosd = bv @ arm
            cl *= 1 - np.exp(-(np.maximum(1 - cosd, 0) / 0.004) ** 1.5) * 0.95
            col = col * (1 - cl[:, None] * 0.85) + 245 * cl[:, None] * 0.85
        if emissive:
            shade = np.ones(len(col), np.float32)
        else:
            ndl = n @ LIGHT
            shade = 0.035 + 0.965 * np.clip(ndl * 1.1 + 0.08, 0, 1) ** 0.85
        col = col * shade[:, None]
        if earth:
            mu = np.clip(-(n * dm).sum(1), 0, 1)
            rim = (1 - mu) ** 2.6 * np.clip(n @ LIGHT + 0.35, 0, 1)
            col = col + np.array([90, 150, 255], np.float32) * rim[:, None] * 0.95
        a = alpha[m][:, None]
        reg[m] = reg[m] * (1 - a) + col * a
    if earth:  # свечение атмосферы снаружи диска
        out = theta > theta_s
        g = np.exp(-np.maximum(theta[out] - theta_s, 0) * F / max(6.0, 0.035 * Rp)) * 0.85
        reg[out] += np.array([70, 130, 255], np.float32) * g[:, None]
    if ring_front is not None:
        front, col, a = ring_front
        reg[front] = reg[front] * (1 - a[:, None]) + col * a[:, None]
    return sx, sy, Rp


def sun_glow(canvas, cam):
    sx, sy, z = cam.proj(np.zeros(3))
    if z <= 0:
        return
    Rp = F * 0.9 / max(float(np.linalg.norm(cam.p)), 1e-3)
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    dd = np.hypot(xs - sx, ys - sy) / max(Rp, 1)
    g = np.clip(1.4 / (dd * dd + 0.6) - 0.02, 0, 3)
    canvas += g[..., None] * np.array([255, 190, 110], np.float32) * 0.9
    dd2 = np.clip(dd - 1, 0, None)
    canvas += (np.exp(-dd2 * 0.9) * 0.6)[..., None] * np.array([255, 150, 60], np.float32)


def orbits(cam, alpha):
    if alpha <= 0.01:
        return None
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    ang = np.linspace(0, 2 * np.pi, 361)
    for name, (r, *_rest) in ORBITS.items():
        P = np.stack([r * np.cos(ang), np.zeros_like(ang), r * np.sin(ang)], -1)
        x, y, z = cam.proj(P)
        for i in range(360):
            if z[i] > 0.05 and z[i + 1] > 0.05:
                d.line((x[i], y[i], x[i + 1], y[i + 1]), fill=(255, 205, 150, int(90 * alpha)), width=2)
    return lay


def neon_layer(lines, fill_polys, strength):
    """Неоновая обводка: белое ядро + абрикосовое и гранатовое свечение."""
    core = Image.new("L", (W, H), 0)
    dc = ImageDraw.Draw(core)
    fill = Image.new("L", (W, H), 0)
    df = ImageDraw.Draw(fill)
    for poly in fill_polys:
        if len(poly) > 2:
            df.polygon(poly, fill=255)
    for seg in lines:
        if len(seg) > 1:
            dc.line(seg, fill=255, width=4, joint="curve")
    g1 = np.asarray(core.filter(ImageFilter.GaussianBlur(5)), np.float32) / 255
    g2 = np.asarray(core.filter(ImageFilter.GaussianBlur(18)), np.float32) / 255
    c = np.asarray(core, np.float32) / 255
    f = np.asarray(fill.filter(ImageFilter.GaussianBlur(3)), np.float32) / 255
    add = (c[..., None] * np.array([255, 240, 225]) + g1[..., None] * np.array([255, 150, 70]) * 2.2
           + g2[..., None] * np.array([230, 40, 70]) * 3.0 + f[..., None] * np.array([180, 40, 60]) * 0.35)
    return add * strength, f


def border_rings():
    g = json.load(open(os.path.join(DIR, "border.json")))
    polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    return [np.array(p[0]) for p in polys]


_RINGS = []
_INNER = []


def rings():
    if not _RINGS:
        _RINGS.extend(border_rings())
    return _RINGS


def inner_lines():
    """Внутренняя граница Армения — Арцах: такая же неоновая линия, без подписей."""
    if not _INNER:
        g = json.load(open(os.path.join(DIR, "inner.json")))
        lines = g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]
        _INNER.extend(np.array(l) for l in lines if len(l) > 1)
    return _INNER


# ================================================================ satellite (Web Mercator)
_SAT = {}


def sat_level(z):
    if z not in _SAT:
        f = glob.glob(os.path.join(DIR, "sat", f"z{z}_*.jpg"))[0]
        _, tx, ty = os.path.basename(f)[:-4].split("_")
        _SAT[z] = (Image.open(os.path.join(DIR, "sat", f"final_z{z}.jpg")).convert("RGB"), int(tx), int(ty))
    return _SAT[z]


def merc(lat, lon, z):
    n = 256 * 2 ** z
    lat = np.radians(lat)
    return (np.asarray(lon) + 180) / 360 * n, (1 - np.log(np.tan(lat) + 1 / np.cos(lat)) / np.pi) / 2 * n


def sat_view(Z, lat, lon):
    def render(L):
        img, tx, ty = sat_level(L)
        cx, cy = merc(lat, lon, L)
        cx -= tx * 256
        cy -= ty * 256
        s = 2 ** (L - Z)
        bw, bh = W * s, H * s
        if bw > img.width or bh > img.height:
            return None
        x0 = min(max(cx - bw / 2, 0), img.width - bw)  # не выходим за край мозаики
        y0 = min(max(cy - bh / 2, 0), img.height - bh)
        return np.asarray(img.resize((W, H), Image.BILINEAR, box=(x0, y0, x0 + bw, y0 + bh)), np.float32)
    hi = min(14, math.ceil(Z))
    lo = max(5, min(hi, math.floor(Z)))
    a = render(hi)
    b = render(lo) if lo != hi else a
    if a is None:
        return b
    # мягкая смена уровня детализации
    k = 1 - smooth((hi - Z - 0.42) / 0.12) if b is not None else 1
    return a * k + b * (1 - k) if k < 1 else a


def screen_of(lat, lon, Z, clat, clon):
    x, y = merc(lat, lon, Z)
    cx, cy = merc(clat, clon, Z)
    return x - cx + W / 2, y - cy + H / 2


MAP_KEYS = [  # (время, Z, тип сглаживания до следующего)
    (8.5, 5.15), (9.8, 7.35), (10.9, 7.75), (12.0, 10.9), (12.7, 11.2), (14.0, 14.3),
]
EASES = [lambda p: 1 - (1 - p) ** 2.2, lambda p: p, eio, lambda p: p, eio]
ARM_C = (40.08, 45.38)  # центр общего контура Армении и Арцаха
VERN = (40.1767, 44.5171)


def map_Z(t):
    for i in range(len(MAP_KEYS) - 1):
        (a, za), (b, zb) = MAP_KEYS[i], MAP_KEYS[i + 1]
        if t <= b:
            return za + (zb - za) * EASES[i](min(1, max(0, (t - a) / (b - a))))
    return MAP_KEYS[-1][1]


def map_center(Z):
    k1 = smooth((Z - 7.7) / 3.2)
    k2 = smooth((Z - 10.9) / 3.0)
    lat = ARM_C[0] + (ARM[0] - ARM_C[0]) * k1 + (VERN[0] - ARM[0]) * k2
    lon = ARM_C[1] + (ARM[1] - ARM_C[1]) * k1 + (VERN[1] - ARM[1]) * k2
    return lat, lon


# ================================================================ main draw
def globe_frame(t, labels=True):
    cam = camera(t)
    canvas = stars(cam) * (1 - smooth((t - 6.5) / 2.0) * 0.6)
    if t < 6.5:
        sun_glow(canvas, cam)
    # рисуем от дальних к ближним
    items = []
    for name, (orb, ang, r, tx, tilt) in ORBITS.items():
        P = ppos(name)
        items.append((float(np.linalg.norm(P - cam.p)), name, P, r, tx, tilt))
    items.append((float(np.linalg.norm(cam.p)), "Солнце", np.zeros(3), 0.9, "2k_sun.jpg", 0))
    moon = EARTH + np.array([0.42, 0.18, -0.30])
    items.append((float(np.linalg.norm(moon - cam.p)), "Луна", moon, 0.052, "2k_moon.jpg", 0))
    items.sort(key=lambda i: -i[0])
    lay = orbits(cam, 1 - smooth((t - 2.6) / 1.2))
    if lay is not None:  # орбиты — под планетами
        a = np.asarray(lay, np.float32)
        canvas[:] = canvas * (1 - a[..., 3:] / 255) + a[..., :3] * (a[..., 3:] / 255)
    marks = []
    for dist, name, P, r, tx, tilt in items:
        if name == "Земля":
            rot = earth_rot(t)
        else:
            rot = roty(t * 0.25 + hash(name) % 7, math.radians(tilt))
        res = draw_sphere(canvas, cam, P, r, tx, rot, emissive=(name == "Солнце"),
                          earth=(name == "Земля"), t=t, ring=(name == "Сатурн"))
        if res and name not in ("Луна",):
            marks.append((name, res))
    img = Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8)).convert("RGBA")
    if labels:
        lab = 1 - smooth((t - 1.6) / 0.6)
        if lab > 0:
            for name, (sx, sy, Rp) in marks:
                if name == "Солнце" or not (0 < sx < W and 0 < sy < H):
                    continue
                s = API["text_sprite"](name, 26, "SemiBold", CREAM)
                API["paste"](img, s, sx + Rp + 6, sy, lab * smooth(t / 0.4), "lm")
        for name, (sx, sy, Rp) in marks:  # подписи планет, мимо которых пролетаем
            if name in ("Сатурн", "Юпитер", "Марс") and 40 < Rp < 700 and 0 < sx < W and t > 1.6:
                o = smooth((Rp - 40) / 40) * (1 - smooth((Rp - 420) / 200))
                s = API["text_sprite"](name.upper(), 40, "ExtraBold", CREAM)
                API["paste"](img, s, sx, sy + Rp + 30, o, "mt")
    # неоновая Армения на глобусе
    k = smooth((t - 7.0) / 0.9)
    if k > 0:
        rot = earth_rot(t)
        segs, polys = [], []
        for ring in rings():
            bv = body_vec(ring[:, 1], ring[:, 0])
            Pw = EARTH + ER * (bv @ rot)
            nrm = Pw - EARTH
            vis = ((cam.p - Pw) * nrm).sum(1) > 0
            x, y, z = cam.proj(Pw)
            pts = [(float(a), float(b)) for a, b in zip(x, y)]
            if vis.all():
                polys.append(pts)
            seg = []
            for p, v in zip(pts, vis):
                if v:
                    seg.append(p)
                elif seg:
                    segs.append(seg)
                    seg = []
            if seg:
                segs.append(seg)
        for ln in inner_lines():
            Pw = EARTH + ER * (body_vec(ln[:, 1], ln[:, 0]) @ rot)
            if (((cam.p - Pw) * (Pw - EARTH)).sum(1) > 0).all():
                x, y, z = cam.proj(Pw)
                segs.append([(float(p), float(q)) for p, q in zip(x, y)])
        pulse = 0.85 + 0.15 * math.sin(t * 9)
        add, fmask = neon_layer(segs, polys, k * pulse)
        a = np.asarray(img.convert("RGB"), np.float32)
        a = a * (1 - 0.35 * k * (1 - np.clip(fmask * 3, 0, 1)))[..., None] + add
        img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).convert("RGBA")
    return img


def map_frame(t):
    Z = map_Z(t)
    lat, lon = map_center(Z)
    a = sat_view(Z, lat, lon)
    # неон и затемнение вокруг Армении на общих планах
    k = smooth((t - 8.6) / 0.3) * (1 - smooth((Z - 9.4) / 1.2))
    if k > 0.01:
        segs, polys = [], []
        for ring in rings():
            x, y = screen_of(ring[:, 1], ring[:, 0], Z, lat, lon)
            pts = [(float(p), float(q)) for p, q in zip(x, y)]
            segs.append(pts + pts[:1])
            polys.append(pts)
        for ln in inner_lines():
            x, y = screen_of(ln[:, 1], ln[:, 0], Z, lat, lon)
            segs.append([(float(p), float(q)) for p, q in zip(x, y)])
        pulse = 0.85 + 0.15 * math.sin(t * 9)
        add, fmask = neon_layer(segs, polys, k * pulse)
        a = a * (1 - 0.45 * k * (1 - np.clip(fmask * 3, 0, 1)))[..., None] + add
    img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).convert("RGBA")
    d = ImageDraw.Draw(img)
    # Ереван — светящаяся точка с пульсом
    ky = smooth((Z - 9.6) / 0.6) * (1 - smooth((Z - 12.6) / 0.6))
    if ky > 0.01:
        x, y = screen_of(ARM[0], ARM[1], Z, lat, lon)
        for i in range(3):
            r = ((t * 1.6 + i / 3) % 1) * 140
            d.ellipse((x - r, y - r, x + r, y + r), outline=APRICOT + (int(230 * ky * (1 - r / 140)),), width=4)
        d.ellipse((x - 11, y - 11, x + 11, y + 11), fill=POM + (int(255 * ky),), outline=CREAM + (int(255 * ky),), width=3)
    # пин Вернисажа
    if t > 13.0:
        x, y = screen_of(VERN[0], VERN[1], Z, lat, lon)
        p = API["ease_back"]((t - 13.0) / 0.35)
        py = y - 70 - (1 - p) * 220
        for i in range(2):
            r = ((t * 1.4 + i / 2) % 1) * 120
            d.ellipse((x - r, y - r * 0.45, x + r, y + r * 0.45), outline=APRICOT + (int(220 * (1 - r / 120)),), width=4)
        d.ellipse((x - 30, py - 30, x + 30, py + 30), fill=POM + (255,), outline=CREAM + (255,), width=4)
        d.polygon([(x - 22, py + 18), (x + 22, py + 18), (x, y)], fill=POM + (255,))
        d.ellipse((x - 11, py - 11, x + 11, py + 11), fill=CREAM + (255,))
    return img


def draw(t, dur):
    if t < 8.5:
        return globe_frame(t)
    m = map_frame(t)
    if t < 9.0:  # вход в атмосферу: глобус → спутник со вспышкой
        g = globe_frame(t, labels=False)
        k = smooth((t - 8.5) / 0.45)
        out = Image.blend(g, m, k)
        fl = math.sin(math.pi * min(1, (t - 8.5) / 0.5)) * 0.55
        out.alpha_composite(Image.new("RGBA", (W, H), (235, 245, 255, int(255 * fl))))
        return out
    return m
