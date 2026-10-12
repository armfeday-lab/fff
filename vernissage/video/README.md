# Рендер ролика

`render.py` собирает динамичный моушн‑ролик по [`../script.md`](../script.md): 1920×1080, 30 fps, ~1:52 с музыкой (2:18 без ускорения), без озвучки, монтаж в бит 120 BPM. Внутри: стеклянный заголовок на фоне летящих гранатов и флагов, приближение к Земле из космоса → неоновая Армения с Арцахом → спутниковый зум до Вернисажа (`space.py`), история 1970→2026 от ч/б к цвету, быстрые наезды и панорамы, whip‑переходы со смазом, zoom‑through, шторки, тряска и вспышки на ударах, слова из фото, триптихи, кинетический текст, карточки рейтингов, зерно.

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

С музыкой — зурна в интро, дудук‑ремикс дальше (Kevin MacLeod, CC BY 4.0, incompetech.com):

```bash
# 1) дорожка: «Old Road» подтягиваем до 120 BPM и ставим удар на 0:00; «Finding the Balance» (150 BPM) — с 0:08
ffmpeg -i "Old Road.mp3" -i "Finding the Balance.mp3" -filter_complex \
  "[0:a]atempo=1.017,atrim=start=0.467:end=9.0,asetpts=PTS-STARTPTS,afade=t=out:st=7.7:d=0.6[a];\
   [1:a]atrim=start=0.37,asetpts=PTS-STARTPTS,adelay=8000|8000,afade=t=out:st=110.0:d=2.0[b];\
   [a][b]amix=inputs=2:normalize=0:duration=longest,atrim=0:112,loudnorm=I=-14:TP=-1.5:LRA=11[o]" \
  -map "[o]" -ar 48000 -ac 2 soundtrack.wav
# 2) после интро картинка ускоряется в 1.25 раза — склейки встают на удары 150 BPM
python3 render.py ... --tail-speed 1.25 --music soundtrack.wav -o vernissage_music.mp4
```

Звуковые эффекты (синтезируются, лицензии не нужны) и финальный микс:

```bash
python3 sfx.py --tail-speed 1.25 -o sfx.wav     # свисты, удары, космос, неон, затвор, колокольчики, гонг…
ffmpeg -i soundtrack.wav -i sfx.wav -filter_complex \
  "[0:a]volume=0.75[m];[m][1:a]amix=inputs=2:normalize=0,alimiter=limit=0.95,loudnorm=I=-14:TP=-1.5:LRA=11" mix.wav
python3 render.py ... --tail-speed 1.25 --music mix.wav -o vernissage_final.mp4
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
