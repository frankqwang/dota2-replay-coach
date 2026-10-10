#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""分析 ReplayDump 输出的逐 tick CSV。"""
import csv, sys
from collections import defaultdict

CORE = {
    1317: '宙斯', 1358: '军团指挥官', 1398: '赏金猎人', 1438: '巨魔战将',
    309: '帕吉', 349: '瘟疫法师', 1478: '食人魔魔法师', 1519: '百戏大王',
    389: '莉娜', 429: '殁境神蚀者',
}
DT = {v: k for k, v in CORE.items()}

rows = defaultdict(list)
team = {}
with open('ticks_9036564967.csv', encoding='utf-8') as f:
    for d in csv.DictReader(f):
        idx = int(d['index'])
        if idx not in CORE:
            continue
        rows[idx].append((float(d['gametime']), float(d['x']), float(d['y']),
                          int(d['hp']), int(d['level']), int(d['lifestate'])))
        team[idx] = int(d['team'])

print('=== 英雄 & 队伍 ===')
for idx in sorted(CORE, key=lambda i: (team.get(i, 0), i)):
    rs = rows[idx]
    if not rs:
        continue
    print('  %-8s idx=%-5d team=%d  样本=%-5d  时间 %.0f-%.0f s' % (
        CORE[idx], idx, team[idx], len(rs), rs[0][0], rs[-1][0]))

# 时间校准：用「等级首次 >= 2」判断对线开始（应为游戏 ~1:00-1:30）
lc = rows[1358]
print()
print('=== 时间校准 ===')
print('  CSV gametime 首个采样 = %.0f s (tick 4170)' % lc[0][0])
first_lvl2 = next((r[0] for r in lc if r[4] >= 2), None)
print('  军团首次 level>=2 于 gametime = %s' % (('%.0f s' % first_lvl2) if first_lvl2 else 'n/a'))
# 首次死亡
first_death = next((r[0] for r in lc if r[5] >= 1), None)
print('  军团首次死亡(lifestate>=1) 于 gametime = %s' % (('%.0f s' % first_death) if first_death else 'n/a'))

print()
print('=== 军团指挥官 对线期轨迹 (每 30s, gametime <= 700) ===')
buckets = defaultdict(list)
for r in lc:
    if r[0] <= 700:
        buckets[int(r[0] // 30)].append(r)
for b in sorted(buckets):
    rs = buckets[b]
    ax = sum(r[1] for r in rs) / len(rs)
    ay = sum(r[2] for r in rs) / len(rs)
    hp = sum(r[3] for r in rs) / len(rs)
    lv = max(r[4] for r in rs)
    dead = any(r[5] >= 1 for r in rs)
    print('  %3d-%3ds  pos=(%6.0f,%6.0f)  avgHP=%5.0f  maxLvl=%2d %s' % (
        b * 30, b * 30 + 30, ax, ay, hp, lv, '  <DEAD>' if dead else ''))

print()
print('=== 军团指挥官 全部死亡时段 ===')
prev_alive = True
start = None
for r in lc:
    alive = r[5] == 0
    if prev_alive and not alive:
        start = r
    elif not prev_alive and alive and start:
        print('  死亡: t=%6.0f-%6.0f s   死前位置 (%6.0f,%6.0f)' % (
            start[0], r[0], start[1], start[2]))
    prev_alive = alive

print()
print('=== 各英雄最终位置(最后一采样) ===')
for idx in sorted(CORE):
    if rows[idx]:
        r = rows[idx][-1]
        print('  %-8s 末次 pos=(%6.0f,%6.0f) hp=%5d lvl=%2d' % (CORE[idx], r[1], r[2], r[3], r[4]))

print()
print('=== 英雄间距离矩阵(游戏第 40 分钟附近) ===')
T = 2400
snap = {}
for idx, rs in rows.items():
    best = min(rs, key=lambda r: abs(r[0] - T))
    if abs(best[0] - T) < 5:
        snap[idx] = best
print('  时刻约 %.0f s, 参战英雄: %s' % (list(snap.values())[0][0] if snap else T,
                                   ','.join(CORE[i] for i in snap)))
