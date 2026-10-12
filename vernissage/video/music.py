#!/usr/bin/env python3
"""Музыкальная дорожка ролика под монтаж render.py.

  python3 music.py --music папка/с/mp3 --duduk duduk.mp3 -o soundtrack.wav

  космос            — «Finding the Balance» (Kevin MacLeod, CC BY 4.0), спокойное начало, затухает к взрыву
  интро и заголовок — «Old Road» (Kevin MacLeod, CC BY 4.0): зурна ровно 120 BPM, удар на старте интро
  ряды и история    — после заголовка зурна плавно уходит в «Desert City» (Kevin MacLeod, CC BY 4.0),
                      замедленную до 80 BPM: такт = 3 с, склейки рядов и каждый год истории — на сильную долю
  знак и Арарат     — без барабанов: «Desert City» тише, сверху живой дудук (freesound.org/s/352572, CC0),
                      фраза поднята на 3 полутона и приходит в тонику трека
  каталог и финал   — зурна плавно возвращается в долю, дхол на каждой склейке; в «02 ДУДУК» зурна
                      тише, сверху дудук с басом 808 в том же темпе
Дудук и зурна в одном ладу (хиджаз от ре) и строе (+10 центов к A440), фразы не транспонируем.
"""
import argparse
import os
import subprocess
import sys
import wave

import numpy as np

SR = 48000
BEAT = 0.5  # 120 BPM
DUDUK_PHRASE = (198.36, 6.0)  # соль# → ре# → ре → до → долгое ре (сцена «02 ДУДУК»)
ARARAT_PHRASE = (127.92, 12.0)  # соль# → фа → ре → до# → до → долгое ре (знак → Арарат)
ZURNA_BACK = 12.0  # с какого такта «Old Road» зурна возвращается в каталоге


def ff(args, out):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args, "-ar", str(SR), "-ac", "2", out], check=True)


def read(path):
    with wave.open(path) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float64) / 32768
    return x.reshape(-1, 2)


def write(path, x):
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


def rms(x):
    return float(np.sqrt(np.mean(x ** 2)) + 1e-9)


# ---------------------------------------------------------------- бас‑секция под дудук
def sat(x, k):
    return np.tanh(x * k) / np.tanh(k)


def b808(freq, dur=0.7, amp=1.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = freq * (1 + 1.2 * np.exp(-t / 0.025))  # короткий «щелчок» сверху вниз
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / (dur * 0.45)) * np.clip(t / 0.003, 0, 1)
    x *= np.clip((dur - t) / 0.03, 0, 1)
    return sat(x, 2.2) * amp  # насыщение даёт обертоны — бас слышно и на телефоне


def kick(amp=1.0):
    n = int(0.25 * SR)
    t = np.arange(n) / SR
    f = 50 + 110 * np.exp(-t / 0.03)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.08) * amp


def clap(rng, amp=1.0):
    from scipy.signal import butter, sosfilt
    n = int(0.25 * SR)
    t = np.arange(n) / SR
    e = sum(np.exp(-np.clip(t - d, 0, None) / 0.008) * (t >= d) for d in (0, 0.011, 0.022)) + np.exp(-t / 0.07) * 0.6
    sos = butter(2, [900, 5000], "bandpass", fs=SR, output="sos")
    return sosfilt(sos, rng.standard_normal(n)) * e * amp


def hat(rng, amp=1.0):
    from scipy.signal import butter, sosfilt
    n = int(0.06 * SR)
    t = np.arange(n) / SR
    sos = butter(2, 7000, "highpass", fs=SR, output="sos")
    return sosfilt(sos, rng.standard_normal(n)) * np.exp(-t / 0.015) * amp


def bass_bed(length, root):
    """Половинный грув 3‑3‑2: 808 на 1, «и» второй, 4‑й; бочка с ним, хлопок на 2 и 4, хэты восьмыми."""
    rng = np.random.default_rng(5)
    mono = np.zeros(int((length + 1) * SR))
    side = np.zeros_like(mono)

    def add(buf, t, snd):
        i = int(t * SR)
        j = min(len(buf), i + len(snd))
        buf[i:j] += snd[: j - i]

    bar = 4 * BEAT
    notes = [root, root, root, root, root, root, root, root * 2 ** (-2 / 12), root]  # в конце — до → ре
    k = 0
    for b in range(int(round(length / bar))):
        for beat in (0.0, 1.5, 3.0):
            t = b * bar + beat * BEAT
            add(mono, t, b808(notes[min(k, len(notes) - 1)], 0.72 if beat < 3 else 0.5))
            add(mono, t, kick(0.55))
            k += 1
        for beat in (1, 3):
            add(mono, b * bar + beat * BEAT, clap(rng, 0.22))
        for e in range(8):
            add(side, b * bar + e * BEAT / 2, hat(rng, 0.07 if e % 2 else 0.11))
    out = np.stack([mono, mono], 1)
    out[:, 0] += side * 0.8
    out[:, 1] += np.roll(side, int(0.004 * SR))  # хэты чуть шире
    return out[: int(length * SR)]


def dhol(rng, amp=1.0):
    """Дхол, басовая сторона: низкий удар с кожей."""
    n = int(0.7 * SR)
    t = np.arange(n) / SR
    body = np.sin(2 * np.pi * np.cumsum(58 + 60 * np.exp(-t / 0.035)) / SR) * np.exp(-t / 0.2)
    from scipy.signal import butter, sosfilt
    skin = sosfilt(butter(2, 700, "lowpass", fs=SR, output="sos"), rng.standard_normal(n)) * np.exp(-t / 0.04) * 0.5
    stick = sosfilt(butter(2, 2500, "highpass", fs=SR, output="sos"), rng.standard_normal(n)) * np.exp(-t / 0.005) * 0.3
    return sat(body + skin + stick, 1.8) * amp


def tek(rng, amp=1.0, f=420.0):
    """Сухой «тэк» по ободу — лёгкая доля между склейками."""
    n = int(0.12 * SR)
    t = np.arange(n) / SR
    from scipy.signal import butter, sosfilt
    tone = np.sin(2 * np.pi * f * t) * np.exp(-t / 0.03)
    snap = sosfilt(butter(2, [1500, 6000], "bandpass", fs=SR, output="sos"), rng.standard_normal(n)) * np.exp(-t / 0.012)
    return (tone * 0.6 + snap) * amp


def percussion(length, t0, cuts, accents, beat, fill_at=None, ticks=True):
    """Перкуссия, которая «считает» монтаж: дхол на каждой склейке; с ticks — ещё «тэк» на долях и тихие восьмые.
    Время — в ролике; доли считаются от t0."""
    rng = np.random.default_rng(9)
    out = np.zeros((int((length + 1) * SR), 2))

    def add(t, snd, pan=0.0):
        i = int(round((t - t0) * SR))
        if i < 0 or i >= len(out):
            return
        j = min(len(out), i + len(snd))
        out[i:j, 0] += snd[: j - i] * (1 - max(0, pan))
        out[i:j, 1] += snd[: j - i] * (1 + min(0, pan))

    strong = sorted({round(c, 3) for c in cuts})
    for c in strong:
        add(c, dhol(rng, 1.0))
    if ticks:
        k = 0
        while k * beat / 2 < length - 1e-6:
            t = t0 + k * beat / 2
            if not any(abs(t - c) < 0.05 for c in strong):
                if k % 2 == 0:
                    add(t, tek(rng, 0.35, 380 if (k // 2) % 2 else 440), 0.3)
                else:
                    add(t, tek(rng, 0.12, 900), -0.4)  # восьмые — тихо, для движения
            k += 1
    for a in accents:
        add(a, tek(rng, 0.45, 520), -0.2)
    if fill_at is not None:  # дробь‑подводка за долю до склейки
        for i in range(4):
            add(fill_at - beat + i * beat / 4, tek(rng, 0.25 + 0.1 * i, 460 + 40 * i), 0.2 * (i % 2 * 2 - 1))
    return out[: int(length * SR)]


def place(dst, at, snd):
    i = int(round(at * SR))
    j = min(len(dst), i + len(snd))
    dst[i:j] += snd[: j - i]


def fades(x, fin=0.0, fout=0.0):
    n = len(x)
    t = np.arange(n) / SR
    e = np.ones(n)
    if fin:
        e *= np.clip(t / fin, 0, 1)
    if fout:
        e *= np.clip((n / SR - t) / fout, 0, 1)
    return x * e[:, None]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--music", required=True, help="папка с «Old Road.mp3», «Finding the Balance.mp3», «Desert City.mp3»")
    ap.add_argument("--duduk", required=True, help="freesound 352572 (Duduk Armenian Sample Sound, CC0)")
    ap.add_argument("--tmp", default=".")
    ap.add_argument("-o", "--out", default="soundtrack.wav")
    a = ap.parse_args()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import render as R

    D, O = R.out_duration(), R.OPEN_LEN
    T1 = R.to_out(11.0)                    # конец заголовка — начало рядов
    He = R.to_out(R.H0 + R.HIST_LEN)       # конец истории: годы превращаются в знак
    C = R.to_out(42.0)                     # каталог
    tmp = lambda n: os.path.join(a.tmp, n)
    m = lambda n: os.path.join(a.music, n)
    ff(["-i", m("Finding the Balance.mp3"), "-af",
        f"atrim=start=0.37:end={0.37 + O},asetpts=PTS-STARTPTS,afade=t=out:st={O - 1.0}:d=1.0"], tmp("_ftb.wav"))
    ff(["-i", m("Old Road.mp3"), "-af", "atempo=1.017,atrim=start=0.467,asetpts=PTS-STARTPTS"], tmp("_zurna.wav"))
    ff(["-i", m("Desert City.mp3"), "-af", f"atempo={80 / 85.97:.5f}"], tmp("_desert.wav"))  # 85.97 → 80 BPM
    ff(["-ss", str(DUDUK_PHRASE[0]), "-t", str(DUDUK_PHRASE[1] + 0.5), "-i", a.duduk, "-af", "highpass=f=120"],
       tmp("_duduk.wav"))
    # фраза для знака и Арарата — на 3 полутона выше (минус 7 центов строя), чтобы прийти в тонику «Desert City» (фа)
    ff(["-ss", str(ARARAT_PHRASE[0]), "-t", str(ARARAT_PHRASE[1]), "-i", a.duduk, "-af",
        f"highpass=f=120,rubberband=pitch={2 ** (293 / 1200):.5f}:formant=preserved"], tmp("_duduk2.wav"))
    ftb, zur, des = read(tmp("_ftb.wav")), read(tmp("_zurna.wav")), read(tmp("_desert.wav"))
    ref = rms(zur[: int(10 * SR)])  # громкость зурны в интро — опора для остальных частей
    out = np.zeros((int(D * SR) + SR, 2))
    out[: len(ftb)] += ftb

    # 1) интро и заголовок: зурна с удара; на последних секундах заголовка плавно уступает «Desert City»
    XF = 3.0  # длина перехода: такт «Desert City» до конца заголовка
    z = zur[: int((T1 - O + 0.75) * SR)]
    tz = O + np.arange(len(z)) / SR
    place(out, O, z * np.cos(np.pi / 2 * np.clip((tz - (T1 - XF)) / (XF + 0.75), 0, 1))[:, None])
    # 2) ряды и история: «Desert City» 80 BPM, её сильная доля (начало трека) — точно на конце заголовка
    d = fades(des[: int((C - T1 + 0.75) * SR)], 0.01, 2.25) * (0.9 * ref / rms(des[: int(30 * SR)]))
    # затакт: второй такт трека подкладываем под конец заголовка и плавно вводим — сильная доля остаётся на склейке
    pre = des[int(3.0 * SR): int((3.0 + XF) * SR)] * (0.9 * ref / rms(des[: int(30 * SR)]))
    pre = pre * (np.sin(np.pi / 2 * np.arange(len(pre)) / len(pre)) ** 2)[:, None]
    place(out, T1 - XF, pre)
    # знак и Арарат: трек не выключаем — он тише уходит под дудук, барабаны молчат
    tt = T1 + np.arange(len(d)) / SR
    duck = 1 - 0.45 * np.clip((tt - He) / 1.5, 0, 1)
    place(out, T1, d * duck[:, None])
    # поверх — перкуссия по монтажу: каждая склейка рядов и каждый год — удар дхола
    Hs = R.to_out(R.H0)
    cuts = [R.to_out(c[0]) for c in R.CL if R.to_out(c[0]) is not None and T1 - 1e-3 <= R.to_out(c[0]) < He]
    cuts += [R.to_out(R.H0 + e * R.ERA) for e in range(len(R.ERAS))]
    accents = [R.to_out(h) for h, amp in R.HITS if R.to_out(h) is not None and T1 < R.to_out(h) < He and amp >= 8]
    perc = percussion(He - T1, T1, cuts, accents, 0.75, fill_at=Hs)
    place(out, T1, perc * (0.75 * ref / rms(perc)))
    # 3) знак и Арарат: без барабанов, сверху живой дудук
    root = 73.42 * 2 ** (10 / 1200)  # ре большой октавы в строе записи (бас под дудуком в каталоге)
    d2 = fades(read(tmp("_duduk2.wav")), 0.05, 1.5)
    d2 *= 0.9 * ref / rms(d2[: int(5 * SR)])
    place(out, He + 1.5, d2)  # дудук вступает, пока годы кружатся, и стихает к каталогу
    # 4) каталог и финал: снова зурна, с сильной доли
    zl = D - C
    # зурна возвращается плавно: вступает за такт до каталога, сильная доля — на склейке
    z = fades(zur[int((ZURNA_BACK - 2.0) * SR): int((ZURNA_BACK + zl) * SR)], 0.0, 2.5)
    tz = np.arange(len(z)) / SR
    z *= (np.sin(np.pi / 2 * np.clip(tz / 2.0, 0, 1)) ** 2)[:, None]
    C0 = C - 2.0
    i0 = int(round(C * SR))
    # вставка дудука с басами в сцене «02 ДУДУК»
    s0, s1 = R.DUDUK_SCENE
    k0, k1 = int(round((R.to_out(s0) - C0) * SR)), int(round((R.to_out(s1) - C0) * SR))
    zref = rms(z[k0 - 6 * SR: k0])
    dud = read(tmp("_duduk.wav"))[: k1 - k0]
    dud = fades(dud, 0.02, 0.35) * (0.8 * zref / rms(dud[: int(4 * SR)]))
    bed = bass_bed((k1 - k0) / SR, root)
    bed *= 0.55 * zref / rms(bed)
    env = np.ones(len(z))  # зурну не выключаем: она тише уходит под дудук и возвращается на «03»
    k = int(0.25 * SR)
    env[k0 - k: k0] = np.linspace(1, 0.45, k)
    env[k0: k1] = 0.45
    env[k1: k1 + k] = np.linspace(0.45, 1, k)
    z = z * env[:, None]
    z[k0: k0 + len(dud)] += dud
    z[k0: k0 + len(bed)] += bed
    # поверх зурны — дхол на каждой склейке каталога
    cuts = [R.to_out(c[0]) for c in R.CL if R.to_out(c[0]) is not None and C - 1e-3 <= R.to_out(c[0]) < D - 0.5]
    perc = percussion(D - C, C, cuts, [], 0.5, ticks=False)
    z[int(2.0 * SR): int(2.0 * SR) + len(perc)] += perc[: len(z) - int(2.0 * SR)] * (0.6 * zref / rms(perc))
    place(out, C0, z)

    write(a.out, out[: int(D * SR)])
    for f in ("_ftb.wav", "_zurna.wav", "_desert.wav", "_duduk.wav", "_duduk2.wav"):
        os.remove(tmp(f))
    print(f"Готово: {a.out} ({D:.1f} с; Desert City {T1:.1f}–{He:.1f}, без бита {He:.1f}–{C:.1f}, зурна с {C:.1f})")


if __name__ == "__main__":
    main()
