#!/usr/bin/env python3
"""Скачивает фото Вернисажа с Wikimedia Commons.

    python3 download_photos.py              # отобранные для сценария (47 шт.), 1920 px
    python3 download_photos.py --all        # все 139 фото из photos_all.csv
    python3 download_photos.py --original   # полный размер вместо 1920 px

По умолчанию качается копия шириной 1920 px — этого хватает для видео 1080p,
и Commons реже ограничивает такие запросы, чем оригиналы.

Файлы сохраняются в папку photos/ рядом со скриптом (она в .gitignore).
Commons ограничивает частоту запросов, поэтому скрипт качает по одному и
ждёт при ответе 429.
"""
import csv
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "photos")
UA = "VernissageResearch/1.0 (https://github.com/armfeday-lab/fff) python-urllib"


def thumb_url(url, width=1920):
    # https://upload.wikimedia.org/wikipedia/commons/0/02/Name.jpg
    #   -> https://upload.wikimedia.org/wikipedia/commons/thumb/0/02/Name.jpg/1920px-Name.jpg
    base, name = url.rsplit("/", 1)
    return base.replace("/commons/", "/commons/thumb/") + f"/{name}/{width}px-{name}"


def fetch(url, path, tries=6):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
                f.write(r.read())
            return True
        except urllib.error.HTTPError as e:
            wait = int(e.headers.get("Retry-After") or 0) or 5 * 2 ** attempt
            if wait > 120:
                print(f"  HTTP {e.code}: Commons просит подождать {wait} с — запустите скрипт позже")
                return False
            print(f"  HTTP {e.code}, жду {wait} с")
            time.sleep(wait)
    return False


def main():
    take_all = "--all" in sys.argv
    original = "--original" in sys.argv
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(HERE, "photos_all.csv"), newline="") as f:
        rows = [r for r in csv.DictReader(f) if take_all or r["selected"] == "yes"]
    for i, r in enumerate(rows, 1):
        path = os.path.join(OUT, r["file"])
        if os.path.exists(path):
            continue
        print(f"[{i}/{len(rows)}] {r['file']}")
        url = r["url"] if original or int(r["w"]) <= 1920 else thumb_url(r["url"])
        if not fetch(url, path):
            print("  не удалось скачать, пропускаю")
        time.sleep(1)
    print(f"Готово: {OUT}")


if __name__ == "__main__":
    main()
