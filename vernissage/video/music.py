#!/usr/bin/env python3
"""Музыкальная дорожка ролика под монтаж render.py.

  python3 music.py --music папка/с/mp3 --duduk duduk.mp3 -o soundtrack.wav

  космос (OPEN_LEN)  — «Finding the Balance» (Kevin MacLeod, CC BY 4.0), спокойное начало, затухает к взрыву
  дальше             — «Old Road» (Kevin MacLeod, CC BY 4.0): зурна, подтянута до ровно 120 BPM, удар на старте интро
  сцена «02 ДУДУК»   — зурна уходит, звучит живой дудук (freesound.org/s/352572, ethnictune, CC0)
                       с басом 808, бочкой, хлопком и тихими хэтами в том же темпе; на «03» зурна возвращается в долю
Дудук и зурна в одном ладу (хиджаз от ре) и строе (+10 центов к A440), фразу не транспонируем.
"""
import argparse
import os
import subprocess
import sys
import wave

import numpy as np

SR = 48000
BEAT = 0.5  # 120 BPM
OLD_ROAD_LEN = 108.06  # длина «Old Road» после atempo и обрезки начала, с
DUDUK_PHRASE = (198.36, 6.0)  # соль# → ре# → ре → до → долгое ре


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--music", required=True, help="папка с «Old Road.mp3» и «Finding the Balance.mp3»")
    ap.add_argument("--duduk", required=True, help="freesound 352572 (Duduk Armenian Sample Sound, CC0)")
    ap.add_argument("--tmp", default=".")
    ap.add_argument("-o", "--out", default="soundtrack.wav")
    a = ap.parse_args()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import render as R

    D, O = R.out_duration(), R.OPEN_LEN
    ZL = D - O
    tmp = lambda n: os.path.join(a.tmp, n)
    old = os.path.join(a.music, "Old Road.mp3")
    # 1) спокойное начало под космос
    ff(["-i", os.path.join(a.music, "Finding the Balance.mp3"), "-af",
        f"atrim=start=0.37:end={0.37 + O},asetpts=PTS-STARTPTS,afade=t=out:st={O - 1.0}:d=1.0"], tmp("_ftb.wav"))
    # 2) зурна ровно 120 BPM; трек короче ролика — продолжаем со второго такта, склейка в долю
    BL = ZL - OLD_ROAD_LEN + 0.2
    ff(["-i", old, "-i", old, "-filter_complex",
        f"[0:a]atempo=1.017,atrim=start=0.467:end={0.467 + OLD_ROAD_LEN},asetpts=PTS-STARTPTS[A];"
        f"[1:a]atempo=1.017,atrim=start=8.467:end={8.467 + BL},asetpts=PTS-STARTPTS[B];"
        f"[A][B]acrossfade=d=0.06:c1=tri:c2=tri,atrim=0:{ZL},afade=t=out:st={ZL - 2.5}:d=2.5"], tmp("_zurna.wav"))
    ftb, zur = read(tmp("_ftb.wav")), read(tmp("_zurna.wav"))

    # 3) вставка дудука: время сцены → время зурны
    s0, s1 = R.DUDUK_SCENE
    g, d0 = 0.0, None
    for start, length in R.SEGMENTS:
        if start <= s0 < start + length:
            d0 = g + s0 - start
        g += length
    z0, z1 = d0 - O, d0 - O + (s1 - s0)
    i0, i1 = int(z0 * SR), int(z1 * SR)
    ref = rms(zur[i0 - 6 * SR: i0])  # громкость зурны перед вставкой

    ff(["-ss", str(DUDUK_PHRASE[0]), "-t", str(DUDUK_PHRASE[1] + 0.5), "-i", a.duduk, "-af", "highpass=f=120"],
       tmp("_duduk.wav"))
    dud = read(tmp("_duduk.wav"))[: i1 - i0]
    n = len(dud)
    t = np.arange(n) / SR
    dud *= (np.clip(t / 0.02, 0, 1) * np.clip((n / SR - t) / 0.35, 0, 1))[:, None]
    dud *= 0.95 * ref / rms(dud[: int(4 * SR)])
    root = 73.42 * 2 ** (10 / 1200)  # ре большой октавы, строй записи
    bed = bass_bed((i1 - i0) / SR, root)
    bed *= 0.7 * ref / rms(bed)

    env = np.ones(len(zur))
    k = int(0.12 * SR)
    env[i0 - k: i0] = np.linspace(1, 0, k)  # зурна уходит за 0.12 с до доли
    env[i0: i1] = 0.0                         # и возвращается ровно на «03»
    zur = zur * env[:, None]
    zur[i0: i0 + n] += dud
    zur[i0: i0 + len(bed)] += bed

    write(a.out, np.concatenate([ftb, zur]))
    for f in ("_ftb.wav", "_zurna.wav", "_duduk.wav"):
        os.remove(tmp(f))
    print(f"Готово: {a.out} ({D:.1f} с; дудук {O + z0:.2f}–{O + z1:.2f} с)")


if __name__ == "__main__":
    main()
