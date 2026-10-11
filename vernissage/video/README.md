# Рендер ролика

`render.py` собирает динамичный моушн‑ролик по [`../script.md`](../script.md): 1920×1080, 30 fps, ~1:52, без озвучки, монтаж в бит 120 BPM. Внутри: быстрые наезды и панорамы, whip‑переходы со смазом, zoom‑through, шторки, тряска и вспышки на ударах, слова из фото, триптихи, кинетический текст, карточки рейтингов, зерно.

## Что нужно

- Python 3 + Pillow + NumPy (`pip install pillow numpy`)
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

- Тайминги и фото сцен — вызовы `clip(...)` в разделе `SCENES`; переходы: `whip`, `whip_r`, `zoom`, `wipe`, `circle`, `up`, `flash`
- Тексты — `T_slam` (влетает с ударом), `T_words`, `T_bar` (плашка), `T_chip`, `T_letters`
- Удары камеры — `hit(t, сила)`
- Кусок ролика для проверки — `--range 40,52`
- Каталог (сцены 9–14) — список `CATALOG`
- Рейтинги — список `RATINGS`, советы — `TIPS`
- Цвета — константы в начале файла (`POM`, `APRICOT`, `CREAM`, …)
