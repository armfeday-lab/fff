# Рендер ролика

`render.py` собирает моушн‑ролик по [`../script.md`](../script.md): 1920×1080, 30 fps, ~2:15, без озвучки. Внутри: наезды камеры на фото, кинетический текст, переходы, карточки рейтингов, чек‑лист.

## Что нужно

- Python 3 + Pillow (`pip install pillow`)
- ffmpeg
- Шрифты Google Fonts: `Montserrat.ttf` и `NotoSansArmenian.ttf` (variable‑версии) — положить в одну папку
- Фото:
  - `vernissage_reviews_shortlist.zip` (Google Карты) — распаковать в папку
  - `vernissage_yandex_shortlist.zip` (Яндекс Карты) — распаковать в папку
  - фото Commons — `python3 ../download_photos.py` (лягут в `../photos/`)

## Запуск

```bash
python3 render.py \
  --google  путь/к/google \
  --yandex  путь/к/yandex \
  --commons ../photos \
  --fonts   путь/к/шрифтам \
  -o vernissage.mp4
```

С музыкой (в конце трек плавно затухает за 2 с):

```bash
python3 render.py ... --music track.mp3 -o vernissage_music.mp4
```

Проверить отдельные кадры, не рендеря весь ролик (сохранит PNG):

```bash
python3 render.py ... --preview 4.5,40,120
```

## Где что менять

- Тайминги и фото сцен — вызовы `seg(...)` в разделе `# ---- scenes`
- Тексты — вызовы `words(...)`, `typewriter(...)`, `chip(...)` в функциях с `@ov`
- Каталог (сцены 9–14) — список `CATALOG`
- Рейтинги — список `RATINGS`, советы — `TIPS`
- Цвета — константы в начале файла (`POM`, `APRICOT`, `CREAM`, …)
