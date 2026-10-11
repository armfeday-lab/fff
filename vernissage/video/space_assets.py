#!/usr/bin/env python3
"""Готовит ассеты для сцены «из космоса» (space.py).

  python3 space_assets.py OUT_DIR

Скачивает и собирает в OUT_DIR:
  tex/            текстуры планет — Solar System Scope, CC BY 4.0
  armenia.json    граница Армении — Natural Earth (общественное достояние)
  sat/z{5..14}_*  мозаики EOxCloudless 2016 (CC BY 4.0) вокруг Вернисажа
  sat/final_z*    они же, где район Еревана/Арарата/Севана заменён свежими
                  безоблачными снимками Copernicus Sentinel‑2 (8 авг. 2025):
                  в мозаике 2016 там цветные полосы

Нужно: pip install pillow numpy rasterio
Подписи для описания видео — см. ../shotlist.md (раздел «Космос и карты»).
"""
import glob
import io
import json
import math
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image, ImageFilter

UA = "VernissageVideo/1.0 (https://github.com/armfeday-lab/fff)"
LAT, LON = 40.1767, 44.5171  # Вернисаж
NX, NY = 12, 7  # размер мозаики в тайлах 256 px
TEXTURES = ["8k_earth_daymap.jpg", "8k_earth_clouds.jpg", "8k_stars_milky_way.jpg", "2k_sun.jpg", "2k_mercury.jpg",
            "2k_venus_atmosphere.jpg", "2k_mars.jpg", "8k_jupiter.jpg", "8k_saturn.jpg", "8k_saturn_ring_alpha.png",
            "2k_uranus.jpg", "2k_neptune.jpg", "2k_moon.jpg"]
S2_ITEMS = ["S2C_38TMK_20250808_0_L2A", "S2C_38TML_20250808_0_L2A", "S2C_38TNK_20250808_0_L2A",
            "S2C_38TNL_20250808_0_L2A", "S2C_38SMJ_20250808_0_L2A", "S2C_38SNJ_20250808_0_L2A",
            "S2C_38SLJ_20250808_0_L2A", "S2C_38TLL_20250808_0_L2A", "S2A_38TLK_20250724_1_L2A"]


def fetch(url, tries=5):
    for k in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120).read()
        except Exception:
            time.sleep(2 * (k + 1))
    raise SystemExit(f"не скачалось: {url}")


def merc_px(lat, lon, z):
    n = 256 * 2 ** z
    return (lon + 180) / 360 * n, (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n


def textures(out):
    os.makedirs(f"{out}/tex", exist_ok=True)
    for n in TEXTURES:
        p = f"{out}/tex/{n}"
        if not os.path.exists(p):
            open(p, "wb").write(fetch(f"https://www.solarsystemscope.com/textures/download/{n}"))


def border(out):
    g = json.loads(fetch("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_countries.geojson"))
    arm = next(f for f in g["features"] if f["properties"].get("ADM0_A3") == "ARM")
    json.dump(arm["geometry"], open(f"{out}/armenia.json", "w"))


def eox(out):
    os.makedirs(f"{out}/sat", exist_ok=True)
    for z in range(5, 15):
        cx, cy = merc_px(LAT, LON, z)
        tx0, ty0 = int(cx // 256) - NX // 2, int(cy // 256) - NY // 2
        jobs = [(tx0 + i, ty0 + j) for j in range(NY) for i in range(NX)]
        url = "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/g/{z}/{y}/{x}.jpg"
        with ThreadPoolExecutor(6) as ex:
            data = list(ex.map(lambda a: fetch(url.format(z=z, x=a[0], y=a[1])), jobs))
        mos = Image.new("RGB", (NX * 256, NY * 256))
        for (x, y), d in zip(jobs, data):
            mos.paste(Image.open(io.BytesIO(d)).convert("RGB"), ((x - tx0) * 256, (y - ty0) * 256))
        mos.save(f"{out}/sat/z{z}_{tx0}_{ty0}.jpg", quality=93)
        print("EOX z", z, flush=True)


def sentinel(out):
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import from_origin
    from rasterio.vrt import WarpedVRT
    os.environ.update(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif")
    hrefs = [json.loads(fetch(f"https://earth-search.aws.element84.com/v1/collections/sentinel-2-l2a/items/{i}"))
             ["assets"]["visual"]["href"] for i in S2_ITEMS]
    R0 = 2 * math.pi * 6378137 / 256
    for z in range(7, 15):
        tx0, ty0 = map(int, os.path.basename(glob.glob(f"{out}/sat/z{z}_*.jpg")[0])[:-4].split("_")[1:])
        res = R0 / 2 ** z
        x0, y0 = tx0 * 256 * res - 20037508.342789244, 20037508.342789244 - ty0 * 256 * res
        ground = res * math.cos(math.radians(LAT))
        ov = None
        for k, r in enumerate([20, 40, 80, 160]):
            if r <= ground:
                ov = k
        for tid, href in zip(S2_ITEMS, hrefs):
            with rasterio.open("/vsicurl/" + href, **({} if ov is None else {"overview_level": ov})) as src:
                with WarpedVRT(src, crs="EPSG:3857", transform=from_origin(x0, y0, res, res), width=NX * 256,
                               height=NY * 256, resampling=Resampling.bilinear, nodata=0) as vrt:
                    a = vrt.read()
            if (a.max(0) > 0).any():
                Image.fromarray(a.transpose(1, 2, 0)).save(f"{out}/sat/tile_{tid[4:9]}_z{z}.png")
        print("S2 z", z, flush=True)


def merge(out):
    tiles = sorted({re.search(r"tile_(\w+)_z", f).group(1) for f in glob.glob(f"{out}/sat/tile_*")})

    def load(t, z):
        p = f"{out}/sat/tile_{t}_z{z}.png"
        return np.asarray(Image.open(p), np.float32) if os.path.exists(p) else None

    # 1) тайлы разных дат — к общему цвету по перекрытиям (эталон — тайл с Ереваном)
    A = {t: load(t, 10) for t in tiles}
    gain = {"38TMK": (np.ones(3), np.zeros(3))}
    todo = [t for t in tiles if t not in gain]
    for _ in range(10):
        for t in list(todo):
            for u, (gu, ou) in list(gain.items()):
                if A[t] is None or A[u] is None:
                    continue
                ov = (A[t].min(2) > 18) & (A[u].min(2) > 18)
                if ov.sum() < 3000:
                    continue
                a, b = A[t][ov], A[u][ov] * gu + ou
                g = b.std(0) / a.std(0)
                gain[t] = (g, b.mean(0) - a.mean(0) * g)
                todo.remove(t)
                break
    for t in todo:
        gain[t] = (np.ones(3), np.zeros(3))
    # 2) вся мозаика — к тонам EOX 2016 (z8)
    base8 = np.asarray(Image.open(glob.glob(f"{out}/sat/z8_*.jpg")[0]).convert("RGB"), np.float32)
    acc = np.zeros_like(base8)
    cnt = np.zeros(base8.shape[:2], np.float32)
    for t in tiles:
        a = load(t, 8)
        if a is not None:
            m = a.min(2) > 18
            g, o = gain[t]
            acc[m] += a[m] * g + o
            cnt[m] += 1
    m = cnt > 0
    gg = np.percentile(base8[m], [10, 90], 0)
    ss = np.percentile(acc[m] / cnt[m][:, None], [10, 90], 0)
    G = (gg[1] - gg[0]) / (ss[1] - ss[0])
    O = gg[0] - ss[0] * G
    for z in range(5, 15):
        f = glob.glob(f"{out}/sat/z{z}_*.jpg")[0]
        base = np.asarray(Image.open(f).convert("RGB"), np.float32)
        if z < 7:
            Image.fromarray(base.astype(np.uint8)).save(f"{out}/sat/final_z{z}.jpg", quality=94)
            continue
        acc = np.zeros_like(base)
        wsum = np.zeros(base.shape[:2], np.float32)
        union = np.zeros(base.shape[:2], np.uint8)
        for t in tiles:
            a = load(t, z)
            if a is None:
                continue
            valid = (a.min(2) > 18).astype(np.uint8) * 255
            union = np.maximum(union, valid)
            w = np.asarray(Image.fromarray(valid).filter(ImageFilter.MinFilter(9 if z < 9 else 31))
                           .filter(ImageFilter.GaussianBlur(25 if z < 11 else 60)), np.float32) / 255
            w = w ** 2
            g, o = gain[t]
            acc += ((a * g + o) * G + O) * w[..., None]
            wsum += w
        s2 = acc / np.maximum(wsum, 1e-4)[..., None]
        cover = np.asarray(Image.fromarray(union).filter(ImageFilter.MinFilter(15)).filter(ImageFilter.GaussianBlur(20)), np.float32) / 255
        if z <= 10:  # на общих планах — круглое «пятно» вокруг Еревана и Севана, без прямых краёв
            tx0, ty0 = map(int, os.path.basename(f)[:-4].split("_")[1:])
            cx, cy = merc_px(40.25, 44.85, z)
            cx, cy = cx - tx0 * 256, cy - ty0 * 256
            kmpx = 40075 * math.cos(math.radians(40.2)) / (256 * 2 ** z)
            yy, xx = np.mgrid[0:base.shape[0], 0:base.shape[1]]
            r = np.clip((175 - np.hypot(xx - cx, yy - cy) * kmpx) / 75, 0, 1)
            cover = cover * r * r * (3 - 2 * r)
        o = base * (1 - cover[..., None]) + np.clip(s2, 0, 255) * cover[..., None]
        Image.fromarray(o.astype(np.uint8)).save(f"{out}/sat/final_z{z}.jpg", quality=94)
        print("merge z", z, flush=True)


if __name__ == "__main__":
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    textures(out)
    border(out)
    eox(out)
    sentinel(out)
    merge(out)
    print("Готово:", out)
