#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""基于逐 tick 坐标做对线站位 + 带线/死亡态势分析。
校准: real_game_seconds = csv_gametime - 229 (由 7 次死亡时刻与 OpenDota 对齐验证)
"""
import csv, math
from collections import defaultdict

OFFSET = 229.0
NAME = {
    1317: '宙斯', 1358: '军团指挥官', 1398: '赏金猎人', 1438: '巨魔战将', 1478: '食人魔魔法师',
    309: '帕吉', 349: '瘟疫法师', 389: '莉娜', 429: '殁境神蚀者', 1519: '百戏大王',
}
ALLY = {1317, 1358, 1398, 1438, 1478}
LC = 1358

# t(round to 0.5s) -> {idx: (x,y,hp,lifestate)}
snap = defaultdict(dict)
with open('ticks_9036564967.csv', encoding='utf-8') as f:
    for d in csv.DictReader(f):
        idx = int(d['index'])
        if idx not in NAME:
            continue
        t = round(float(d['gametime']), 1)
        snap[t][idx] = (float(d['x']), float(d['y']), int(d['hp']), int(d['lifestate']))

times = sorted(snap)
print('采样点: %d, gametime %.0f-%.0f s (真实 %.0f-%.0f s)' % (
    len(times), times[0], times[-1], times[0] - OFFSET, times[-1] - OFFSET))


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def closest(d, t, me_idx, group):
    me = d.get(me_idx)
    if not me:
        return None
    best = None
    for i, p in d.items():
        if i == me_idx or i not in group:
            continue
        dd = dist(me, p)
        if best is None or dd < best[1]:
            best = (i, dd, p)
    return best


def rs(t):  # real seconds label
    return '%d:%02d' % (int(t) // 60, int(t) % 60)


# ---------- 对线段: 每 30 秒最近敌人 ----------
print()
print('=== 对线期 (真实 0:00-8:00) 军团 vs 最近敌人 ===')
for b in range(229, 709, 30):
    key = min(times, key=lambda x: abs(x - b))
    d = snap[key]
    me = d.get(LC)
    if not me:
        continue
    e = closest(d, key, LC, set(NAME) - ALLY)
    a = closest(d, key, LC, ALLY)
    print('  %s  LC=(%6.0f,%6.0f) hp=%4d | 最近敌 %-6s %5.0f | 最近友 %-6s %5.0f' % (
        rs(key - OFFSET), me[0], me[1], me[2],
        NAME[e[0]] if e else '-', e[1] if e else -1,
        NAME[a[0]] if a else '-', a[1] if a else -1))

# ---------- 死亡态势 ----------
print()
print('=== 每次死亡时的战场态势 (真实时间) ===')
deaths = []
prev = True
start = None
lc_series = [(t, snap[t][LC]) for t in times if LC in snap[t]]
for t, p in lc_series:
    alive = p[3] == 0
    if prev and not alive:
        start = t
    elif not prev and alive and start is not None:
        deaths.append((start, t))
        prev = alive
        start = None
        continue
    prev = alive

for st, en in deaths:
    key = min(times, key=lambda x: abs(x - st))
    d = snap[key]
    me = d.get(LC)
    if not me:
        continue
    print('\n  死亡 @ 真实 %s (csv %.0f)  位置 (%6.0f,%6.0f)' % (
        rs(st - OFFSET), st, me[0], me[1]))
    enemies = sorted(((i, dist(me, p), p) for i, p in d.items()
                      if i not in ALLY), key=lambda x: x[1])
    allies = sorted(((i, dist(me, p), p) for i, p in d.items()
                     if i in ALLY and i != LC), key=lambda x: x[1])
    for i, dd, p in enemies[:3]:
        print('      敌 %-8s 距离 %5.0f  (hp %5d)' % (NAME[i], dd, p[2]))
    for i, dd, p in allies[:3]:
        print('      友 %-8s 距离 %5.0f  (hp %5d)' % (NAME[i], dd, p[2]))

# ---------- 死亡前 60 秒的移动轨迹 ----------
print()
print('=== 每次死亡前 90 秒 军团的移动轨迹 ===')
for st, en in deaths:
    seg = [(t, snap[t][LC]) for t, _ in lc_series if st - 90 <= t <= st + 5 and LC in snap[t]]
    if not seg:
        continue
    pts = ['%s:(%.0f,%.0f)' % (rs(t - OFFSET), p[0], p[1]) for t, p in seg[::12]]
    print('  [%s 死亡] ' % rs(st - OFFSET) + ' -> '.join(pts))
