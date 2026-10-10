#!/usr/bin/env python
"""fetch_replay.py -- download a Dota 2 replay by match id and decompress it to .dem

zstd support: uses `compression.zstd` from the standard library on Python 3.14+, and
falls back to the `zstandard` package (`pip install zstandard`) on older versions.

  python fetch_replay.py <match_id> [out_dir]

Steps:
1. GET OpenDota /api/matches/{id}; reuse `replay_url` when already present (common: cache hit)
2. otherwise POST /api/request/{id} to trigger the retriever and poll until `replay_url` is
   filled in (up to ~120s)
3. download the replay and detect the real compression by MAGIC BYTES, not by extension
   (zstd = 28 b5 2f fd, bzip2 = BZh); Valve serves zstd data under a `.bz2` name
4. verify the `PBDEMS2` header, and save the OpenDota metadata as od_<id>.json
Output: <out_dir>/<match_id>.dem  (out_dir defaults to the current directory)
"""
import json
import sys
import time
import urllib.request
import bz2
import pathlib

# zstd decompression: prefer the stdlib module (Python 3.14+), fall back to the
# `zstandard` package, and fail with a clear message if neither is present.
try:
    import compression.zstd as zstd          # Python 3.14+
    _ZSTD_DECOMPRESS = zstd.decompress
except ImportError:
    try:
        import zstandard as _zstandard       # pip install zstandard
        _ZSTD_DECOMPRESS = _zstandard.ZstdDecompressor().decompress
    except ImportError:
        _ZSTD_DECOMPRESS = None

API = "https://api.opendota.com/api"
HEADERS = {"User-Agent": "Mozilla/5.0 (dota-replay-pipeline)"}


def http_json(url, method="GET", timeout=30):
    req = urllib.request.Request(url, method=method, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def http_bytes(url, timeout=300):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    match_id = sys.argv[1]
    out_dir = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else ".")
    out_dir.mkdir(parents=True, exist_ok=True)
    dem_path = out_dir / f"{match_id}.dem"
    if dem_path.exists() and dem_path.stat().st_size > 1000:
        print(f"[skip] {dem_path} 已存在")
        return

    # 1. 元数据
    meta = http_json(f"{API}/matches/{match_id}")
    (out_dir / f"od_{match_id}.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    print(f"[meta] duration={meta.get('duration')} radiant_win={meta.get('radiant_win')}")
    for p in meta.get("players", []):
        print(f"  slot={p.get('player_slot'):3d} {p.get('personaname') or p.get('name')} "
              f"hero_id={p.get('hero_id')} {p.get('kills')}/{p.get('deaths')}/{p.get('assists')}")

    # 2. replay_url（缓存命中则跳过 retriever）
    url = meta.get("replay_url")
    if not url:
        print("[req] 触发 retriever ...")
        try:
            http_json(f"{API}/request/{match_id}", method="POST")
        except Exception as e:
            print(f"[warn] request 端点失败（可能已在队列）: {e}")
        for i in range(24):  # 最长 ~120s
            time.sleep(5)
            meta = http_json(f"{API}/matches/{match_id}")
            url = meta.get("replay_url")
            if url:
                break
            print(f"[poll] {i+1} ... 无 replay_url")
    if not url:
        print("[fail] 未拿到 replay_url，稍后重试或换源（Valve 偶发 502）")
        sys.exit(2)

    # 3. 下载 + 按魔数解压
    print(f"[dl] {url}")
    for attempt in range(3):
        try:
            blob = http_bytes(url)
            break
        except Exception as e:
            print(f"[retry {attempt+1}] {e}")
            time.sleep(3)
    else:
        sys.exit(3)

    print(f"[dl] {len(blob)/1e6:.1f} MB, 魔数 {blob[:4].hex()}")
    if blob[:4] == b"\x28\xb5\x2f\xfd":  # 实际是 zstd
        if _ZSTD_DECOMPRESS is None:
            sys.exit("需要 zstd 解压支持：请用 Python 3.14+，或 `pip install zstandard`")
        dem = _ZSTD_DECOMPRESS(blob)
    elif blob[:3] == b"BZh":
        dem = bz2.decompress(blob)
    else:
        dem = blob  # 未压缩
    assert dem[:7] == b"PBDEMS2", f"文件头异常: {dem[:8]!r}"
    dem_path.write_bytes(dem)
    print(f"[done] {dem_path} ({len(dem)/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
