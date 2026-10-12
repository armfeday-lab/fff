#!/usr/bin/env python3
"""Музыкальная дорожка ролика под монтаж render.py.

  python3 music.py --music папка/с/mp3 --duduk duduk.mp3 -o soundtrack.wav

  космос            — «Finding the Balance» (Kevin MacLeod, CC BY 4.0), спокойное начало, затухает к взрыву
  интро и заголовок — «Old Road» (Kevin MacLeod, CC BY 4.0): зурна ровно 120 BPM, удар на старте интро
  ряды и история    — после заголовка зурна плавно уходит в «Desert City» (Kevin MacLeod, CC BY 4.0),
                      замедленную до 80 BPM: такт = 3 с, склейки рядов и каждый год истории — на сильную долю
  знак и Арарат     — без бита: низкий гул‑дам и живой дудук (freesound.org/s/352572, ethnictune, CC0)
  каталог и финал   — снова зурна в долю; в сцене «02 ДУДУК» — дудук с басом 808 в том же темпе
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
ARARAT_PHRASE = (127.92, 11.0)  # соль# → фа → ре → до# → до → долгое ре (знак → Арарат)
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


def dam(length, root):
    """Дам — тянущийся бурдон дудука: мягкая трость на ре и суб октавой ниже, медленно дышит."""
    n = int(length * SR)
    t = np.arange(n) / SR
    reed = sum(np.sin(2 * np.pi * root * 2 * k * t + 0.3 * k) / k ** 1.3 for k in range(1, 7))
    sub = np.sin(2 * np.pi * root * t)
    breath = 0.85 + 0.15 * np.sin(2 * np.pi * 0.23 * t)
    x = (reed * 0.25 + sub * 0.6) * breath
    x *= np.clip(t / 2.5, 0, 1) * np.clip((length - t) / 0.8, 0, 1)
    return np.stack([x, x * 0.97], 1)


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
    ff(["-ss", str(ARARAT_PHRASE[0]), "-t", str(ARARAT_PHRASE[1]), "-i", a.duduk, "-af", "highpass=f=120"],
       tmp("_duduk2.wav"))
    ftb, zur, des = read(tmp("_ftb.wav")), read(tmp("_zurna.wav")), read(tmp("_desert.wav"))
    ref = rms(zur[: int(10 * SR)])  # громкость зурны в интро — опора для остальных частей
    out = np.zeros((int(D * SR) + SR, 2))
    out[: len(ftb)] += ftb

    # 1) интро и заголовок: зурна с удара; после заголовка плавно уходит за 1.5 с
    z = zur[: int((T1 - O + 1.25) * SR)]
    z = z * np.clip((T1 - O + 1.25 - np.arange(len(z)) / SR) / 1.5, 0, 1)[:, None]
    place(out, O, z)
    # 2) ряды и история: «Desert City» 80 BPM, её сильная доля (начало трека) — точно на конце заголовка
    d = fades(des[: int((He - T1 + 1.2) * SR)], 0.01, 1.2)  # последний такт затихает, пока годы кружатся
    place(out, T1, d * (0.9 * ref / rms(des[: int(30 * SR)])))
    # 3) знак и Арарат: без бита — дам и дудук
    root = 73.42 * 2 ** (10 / 1200)  # ре большой октавы в строе записи
    place(out, He - 0.3, dam(C - He + 0.3, root) * (0.35 * ref / 0.3))
    d2 = fades(read(tmp("_duduk2.wav")), 0.05, 1.5)
    d2 *= 0.9 * ref / rms(d2[: int(5 * SR)])
    place(out, C - ARARAT_PHRASE[1], d2)  # фраза начинается, когда складывается золотой знак, и стихает к каталогу
    # 4) каталог и финал: снова зурна, с сильной доли
    zl = D - C
    z = fades(zur[int(ZURNA_BACK * SR): int((ZURNA_BACK + zl) * SR)], 0.01, 2.5)
    i0 = int(round(C * SR))
    # вставка дудука с басами в сцене «02 ДУДУК»
    s0, s1 = R.DUDUK_SCENE
    k0, k1 = int(round((R.to_out(s0) - C) * SR)), int(round((R.to_out(s1) - C) * SR))
    zref = rms(z[k0 - 6 * SR: k0])
    dud = read(tmp("_duduk.wav"))[: k1 - k0]
    dud = fades(dud, 0.02, 0.35) * (0.95 * zref / rms(dud[: int(4 * SR)]))
    bed = bass_bed((k1 - k0) / SR, root)
    bed *= 0.7 * zref / rms(bed)
    env = np.ones(len(z))
    k = int(0.12 * SR)
    env[k0 - k: k0] = np.linspace(1, 0, k)  # зурна уходит за 0.12 с до доли
    env[k0: k1] = 0.0                         # и возвращается ровно на «03»
    z = z * env[:, None]
    z[k0: k0 + len(dud)] += dud
    z[k0: k0 + len(bed)] += bed
    place(out, C, z)

    write(a.out, out[: int(D * SR)])
    for f in ("_ftb.wav", "_zurna.wav", "_desert.wav", "_duduk.wav", "_duduk2.wav"):
        os.remove(tmp(f))
    print(f"Готово: {a.out} ({D:.1f} с; Desert City {T1:.1f}–{He:.1f}, без бита {He:.1f}–{C:.1f}, зурна с {C:.1f})")


if __name__ == "__main__":
    main()
