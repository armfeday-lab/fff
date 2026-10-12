# Рендер ролика

`render.py` собирает динамичный моушн‑ролик по [`../script.md`](../script.md): 1920×1080, 30 fps, ~2:38, без озвучки, монтаж в бит 120 BPM. Внутри: стеклянный заголовок на фоне летящих гранатов и флагов, приближение к Земле из космоса → неоновая Армения с Арцахом → спутниковый зум до Вернисажа (`space.py`), история 1970→2026 от ч/б к цвету, быстрые наезды и панорамы, whip‑переходы со смазом, zoom‑through, шторки, тряска и вспышки на ударах, слова из фото, триптихи, кинетический текст, карточки рейтингов, зерно.

## Что нужно

- Python 3 + Pillow + NumPy (`pip install pillow numpy`), для подготовки космоса ещё `rasterio`
- ffmpeg
- Шрифты Google Fonts: `Montserrat.ttf` и `NotoSansArmenian.ttf` (variable‑версии) — положить в одну папку
- Фото:
  - `vernissage_reviews_shortlist.zip` (Google Карты) — распаковать в папку
  - `vernissage_yandex_shortlist.zip` (Яндекс Карты) — распаковать в папку
  - фото Commons — `python3 ../download_photos.py` (лягут в `../photos/`)

## Ассеты сцены «из космоса»

```bash
python3 space_assets.py путь/к/space   # текстуры планет, граница Армении, спутниковые мозаики (~150 МБ)
```

## Запуск

```bash
python3 render.py \
  --google  путь/к/google \
  --yandex  путь/к/yandex \
  --commons ../photos \
  --fonts   путь/к/шрифтам \
  --space   путь/к/space \
  -o vernissage.mp4
```

С музыкой (Kevin MacLeod, CC BY 4.0, incompetech.com; дудук — freesound.org/s/352572, CC0): «Finding the Balance» под космос, дальше зурна «Old Road» ровно 120 BPM, в сцене «02 ДУДУК» — живой дудук с басом 808 в том же темпе. Длины считаются по монтажу render.py:

```bash
python3 music.py --music папка/с/mp3 --duduk 352572_6510257-hq.mp3 -o soundtrack.wav
python3 sfx.py -o sfx.wav     # свисты, удары и щелчки вспышек в интро, космос, затвор, колокол…
ffmpeg -i soundtrack.wav -i sfx.wav -filter_complex \
  "[0][1]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.95,loudnorm=I=-14:TP=-1.5:LRA=9" mix.wav
python3 render.py ... --music mix.wav -o vernissage_final.mp4
```

Свой трек (в конце плавно затухает за 2 с):

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
