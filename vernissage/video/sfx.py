#!/usr/bin/env python3
"""Звуковые эффекты ролика: синтезируются с нуля (никаких лицензий) и ставятся
точно на события монтажа — берутся из таймлайна render.py.

  python3 sfx.py --tail-speed 1.25 -o sfx.wav
  ffmpeg -i soundtrack.wav -i sfx.wav -filter_complex "[0][1]amix=inputs=2:normalize=0,loudnorm=I=-14:TP=-1.5" mix.wav

Что звучит:
  переходы whip/up      — свист со смазом и панорамой
  zoom / circle / wipe  — «пролёт сквозь» с низким ударом / обратный свист / шорох
  удары (hit)           — низкий «тук» по силе удара; вспышки — щелчок
  космос                — гул и мерцание, нарастание к входу в атмосферу, бум
  неон Армении          — электрический треск; Ереван — сонар; пин — «поп»
  история               — затвор камеры и тиканье счётчика лет
  знак вечности         — 8 колокольчиков (по ветви), мерцание кольца, гонг на золоте
  рейтинги / советы     — тики счётчика, щелчки галочек
"""
import argparse
import math
import os
import sys

import numpy as np
from scipy.signal import butter, sosfilt

SR = 48000
RNG = np.random.default_rng(11)


# ================================================================ синтез
def env(n, a=0.005, r=None, curve=4.0):
    t = np.arange(n) / SR
    att = np.clip(t / max(a, 1e-4), 0, 1)
    if r is None:
        return att
    return att * np.exp(-t / r * curve / 4)


def bp(x, lo, hi, order=2):
    sos = butter(order, [max(20, lo), min(SR / 2 - 100, hi)], "bandpass", fs=SR, output="sos")
    return sosfilt(sos, x)


def lp(x, f, order=2):
    return sosfilt(butter(order, min(f, SR / 2 - 100), "lowpass", fs=SR, output="sos"), x)


def hp(x, f, order=2):
    return sosfilt(butter(order, max(20, f), "highpass", fs=SR, output="sos"), x)


def sweep_noise(dur, f0, f1, q=1.5):
    """Шум, полоса которого ползёт f0→f1 (блоками с перекрытием)."""
    n = int(dur * SR)
    noise = RNG.standard_normal(n + SR)
    out = np.zeros(n)
    blk = 1024
    win = np.hanning(blk * 2)
    for i in range(0, n, blk):
        p = i / n
        f = f0 * (f1 / f0) ** p
        seg = bp(noise[i:i + blk * 2 + 2048], f / q, f * q)[2048 // 2: 2048 // 2 + blk * 2]
        if len(seg) < blk * 2:
            seg = np.pad(seg, (0, blk * 2 - len(seg)))
        j = min(n, i + blk * 2)
        out[i:j] += (seg * win)[: j - i]
    return out / (np.abs(out).max() + 1e-9)


def whoosh(dur=0.45, up=True, pan=(-0.8, 0.8)):
    n = int(dur * SR)
    x = sweep_noise(dur, 300 if up else 3500, 3500 if up else 300)
    t = np.linspace(0, 1, n)
    e = np.sin(np.pi * t) ** 1.6
    return stereo(x * e * 0.55, np.linspace(pan[0], pan[1], n))


def impact(amp=1.0, f0=70, f1=38, dur=0.45):
    n = int(dur * SR)
    t = np.arange(n) / SR
    ph = 2 * np.pi * np.cumsum(f0 * (f1 / f0) ** (t / dur)) / SR
    body = np.sin(ph) * np.exp(-t / (dur * 0.35))
    click = lp(RNG.standard_normal(n), 2500) * np.exp(-t / 0.012) * 0.6
    return stereo((body + click) * 0.9 * amp)


def boom(amp=1.0, dur=1.6):
    n = int(dur * SR)
    t = np.arange(n) / SR
    ph = 2 * np.pi * np.cumsum(55 * (26 / 55) ** (t / dur)) / SR
    body = np.sin(ph) * np.exp(-t / 0.55)
    rumble = lp(RNG.standard_normal(n), 180) * np.exp(-t / 0.7) * 1.5
    crack = hp(RNG.standard_normal(n), 1500) * np.exp(-t / 0.05) * 0.25
    return stereo((body + rumble + crack) * amp)


def click(amp=0.5, f=2400):
    n = int(0.03 * SR)
    t = np.arange(n) / SR
    x = hp(RNG.standard_normal(n), 3000) * np.exp(-t / 0.002) + np.sin(2 * np.pi * f * t) * np.exp(-t / 0.006) * 0.5
    return stereo(x * amp)


def tick(amp=0.25, f=3200):
    n = int(0.02 * SR)
    t = np.arange(n) / SR
    return stereo(np.sin(2 * np.pi * f * t) * np.exp(-t / 0.003) * amp)


def shutter(amp=0.6):
    a = click(amp, 1800)
    out = np.zeros((int(0.09 * SR), 2))
    out[: len(a)] += a
    out[int(0.045 * SR): int(0.045 * SR) + len(a)] += click(amp * 0.8, 1400)
    return out


def paper(amp=0.5):
    n = int(0.12 * SR)
    t = np.arange(n) / SR
    return stereo(bp(RNG.standard_normal(n), 800, 4000) * np.exp(-t / 0.03) * amp)


def riser(dur=1.7, amp=0.6):
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = sweep_noise(dur, 200, 6000, 1.3) * (t / dur) ** 2
    ph = 2 * np.pi * np.cumsum(180 * (720 / 180) ** (t / dur)) / SR
    tone = np.sin(ph) * (t / dur) ** 2.5 * 0.25
    return stereo((x + tone) * amp)


def rumble(dur, amp=0.35):
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = lp(np.cumsum(RNG.standard_normal(n)) * 0.02, 120)
    x /= np.abs(x).max() + 1e-9
    pad = sum(np.sin(2 * np.pi * f * t + RNG.uniform(0, 6)) for f in (55, 82.5, 110)) / 3
    lfo = 0.75 + 0.25 * np.sin(2 * np.pi * 0.25 * t)
    fade = np.clip(t / 1.0, 0, 1) * np.clip((dur - t) / 0.6, 0, 1)
    sparkle = hp(RNG.standard_normal(n), 6000) * (RNG.random(n) > 0.9995) * 3
    return stereo((x * 0.7 + pad * 0.35) * lfo * fade * amp) + stereo(sparkle * 0.15, RNG.uniform(-1, 1, n))


def zap(dur=0.7, amp=0.4):
    n = int(dur * SR)
    t = np.arange(n) / SR
    saw = ((t * 100) % 1) * 2 - 1
    hum = lp(saw, 1800) * (0.6 + 0.4 * (RNG.random(n) > 0.5).astype(float))
    crackle = hp(RNG.standard_normal(n), 2500) * (RNG.random(n) > 0.995) * 4
    flick = np.repeat(RNG.random(n // 480 + 1) > 0.25, 480)[:n].astype(float)
    e = np.clip(t / 0.02, 0, 1) * np.exp(-t / dur * 2.2)
    return stereo((hum * flick + crackle * 0.5) * e * amp)


def bell(freq, dur=1.6, amp=0.35):
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = sum(a * np.sin(2 * np.pi * freq * m * t) * np.exp(-t / (dur * d))
            for m, a, d in ((1, 1, 0.5), (2.76, 0.45, 0.25), (5.4, 0.25, 0.12), (8.93, 0.12, 0.06)))
    return stereo(x * np.clip(t / 0.002, 0, 1) * amp)


def ping(amp=0.3):
    a, b = bell(1320, 1.2, amp) * 0.8, bell(2640, 0.6, amp * 0.3)
    a[: len(b)] += b
    return a


def pop(amp=0.5):
    n = int(0.09 * SR)
    t = np.arange(n) / SR
    ph = 2 * np.pi * np.cumsum(900 * (260 / 900) ** (t / 0.09)) / SR
    return stereo(np.sin(ph) * np.exp(-t / 0.03) * amp)


def shimmer(dur=1.4, amp=0.25):
    n = int(dur * SR)
    out = np.zeros(n)
    for _ in range(60):
        f = RNG.uniform(2500, 7000)
        s = int(RNG.uniform(0, dur - 0.2) * SR)
        m = int(0.18 * SR)
        t = np.arange(m) / SR
        out[s:s + m] += np.sin(2 * np.pi * f * t) * np.exp(-t / 0.05) * RNG.uniform(0.3, 1)
    t = np.arange(n) / SR
    return stereo(out * np.sin(np.pi * t / dur) * amp / 6, RNG.uniform(-0.7, 0.7, n))


def gong(amp=0.6, dur=3.5):
    n = int(dur * SR)
    t = np.arange(n) / SR
    base = 98
    x = sum(a * np.sin(2 * np.pi * base * m * t + RNG.uniform(0, 6)) * np.exp(-t / (dur * d))
            for m, a, d in ((1, 1, 0.45), (1.48, 0.6, 0.35), (2.05, 0.5, 0.3), (2.94, 0.35, 0.22), (4.1, 0.2, 0.15)))
    swell = np.clip(t / 0.01, 0, 1) * (1 + 0.15 * np.sin(2 * np.pi * 3 * t) * np.exp(-t / 1.5))
    return stereo(x * swell * amp * 0.5)


def stereo(x, pan=0.0):
    pan = np.asarray(pan, float)
    l = x * np.cos((pan + 1) * np.pi / 4)
    r = x * np.sin((pan + 1) * np.pi / 4)
    return np.stack([l, r], 1) * math.sqrt(2)


# ================================================================ привязка к монтажу
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tail-speed", type=float, default=1.0)
    ap.add_argument("-o", "--out", default="sfx.wav")
    a = ap.parse_args()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import render as R
    import space as SPACE
    R.TAIL_SPEED = a.tail_speed
    total = R.out_duration()
    buf = np.zeros((int(total * SR) + SR * 4, 2))

    def to_out(ts):
        g = 0.0
        for start, length in R.SEGMENTS:
            if start <= ts < start + length + 1e-6:
                T = g + (ts - start)
                return T if T <= R.INTRO_LEN else R.INTRO_LEN + (T - R.INTRO_LEN) / R.TAIL_SPEED
            g += length
        return None

    def put(ts, snd, gain=1.0, lead=0.0):
        T = to_out(ts)
        if T is None:
            return
        i = int(max(0.0, T - lead) * SR)
        j = min(len(buf), i + len(snd))
        buf[i:j] += snd[: j - i] * gain

    # переходы между клипами
    for t0, t1, fn, tr, td, prev in R.CL:
        mid = t0 + td / 2
        if tr in ("whip", "whip_r"):
            put(mid, whoosh(0.42, True, (-0.9, 0.9) if tr == "whip" else (0.9, -0.9)), 0.8, 0.21)
        elif tr == "up":
            put(mid, whoosh(0.5, True, (0, 0)), 0.8, 0.25)
        elif tr == "zoom":
            put(mid, whoosh(0.5, True, (0, 0)), 0.9, 0.3)
            put(t0 + td * 0.5, impact(0.6, 90, 45, 0.35), 0.8)
        elif tr == "circle":
            put(mid, whoosh(0.5, False, (0, 0)), 0.7, 0.25)
        elif tr == "wipe":
            put(mid, whoosh(0.45, False, (-0.9, 0.9)), 0.7, 0.22)
    for t, amp in R.HITS:
        put(t, impact(min(1.0, amp / 16) * 0.9), 0.75)
    for t, amp in R.FLASHES:
        put(t, click(0.45 * amp), 1.0)

    # космос
    SP0, GL = R.SP0, SPACE.GLOBE_LEN
    put(SP0, rumble(GL + 0.6, 0.4), 1.0)
    put(SP0 + GL - 1.7, riser(1.7, 0.55), 1.0)
    put(SP0 + GL, boom(1.0), 1.0)
    put(SP0 + GL, whoosh(0.7, False, (0, 0)), 0.9)
    put(SP0 + 3.5, zap(0.9, 0.45), 1.0)                          # неон на глобусе
    put(SP0 + 9.3 - SPACE.MAP_SHIFT, zap(0.8, 0.35), 1.0)        # «АРМЕНИЯ»
    for k in range(3):
        put(SP0 + 9.9 - SPACE.MAP_SHIFT + k * 0.6, ping(0.25), 1.0)  # сонар Еревана
    put(SP0 + 13.0 - SPACE.MAP_SHIFT, pop(0.6), 1.0)             # пин Вернисажа

    # история: затвор на каждую эпоху + тиканье счётчика лет
    for e in range(len(R.ERAS)):
        a0 = R.H0 + e * R.ERA
        put(a0 + 0.02, shutter(0.5), 1.0)
        for k in range(8):
            put(a0 + k * 0.055, tick(0.18, 2800 + k * 60), 1.0)
        for i in range(len(R.ERAS[e][5])):
            put(a0 + 0.35 + i * 0.35 + 0.2, paper(0.45), 1.0)

    # знак вечности: ветви — колокольчики по пентатонике, кольцо — мерцание, золото — гонг
    S0 = R.SYM0
    put(S0 + 0.3, whoosh(0.9, True, (-0.5, 0.5)), 0.6)
    put(S0 + 0.8, rumble(2.0, 0.25), 1.0)
    notes = [440, 523.25, 587.33, 659.25, 783.99, 880, 1046.5, 1174.66]
    for k, f in enumerate(notes):
        put(S0 + 2.3 + k * 0.16, bell(f, 1.6, 0.28), 1.0)
    put(S0 + 3.7, shimmer(1.2, 0.3), 1.0)
    put(S0 + 4.3, gong(0.75), 1.0)
    put(S0 + 4.3, shimmer(1.6, 0.25), 1.0)

    # рейтинги, советы, финал
    for i in range(5):
        a0 = 92.9 + i * R.B
        put(a0, whoosh(0.25, True, (0.6, -0.6)), 0.4, 0.1)
        for k in range(6):
            put(a0 + 0.1 + k * 0.12, tick(0.15, 3000 + k * 120), 1.0)
    for i in range(3):
        put(100.0 + i * 2.0 + 0.15, click(0.5, 1600), 1.0)
    put(108.2, pop(0.5), 1.0)

    # уровень: громкие события (свисты, удары) — около 0.6, гонг и бум мягко ограничиваются
    ref = np.percentile(np.abs(buf[np.abs(buf) > 1e-4]), 99.5)
    buf = np.tanh(buf / max(ref, 1e-9) * 0.6 * 1.2) / 1.2
    buf = buf[: int(total * SR)]
    import wave
    with wave.open(a.out, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(buf, -1, 1) * 32767).astype("<i2").tobytes())
    print(f"Готово: {a.out} ({total:.1f} с)")


if __name__ == "__main__":
    main()
