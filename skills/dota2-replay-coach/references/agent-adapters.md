# Agent adapters — agent- and model-specific details

`SKILL.md` only names **capabilities**. This file covers the things that genuinely differ between
agents and models: how much context to spend, and what has to be installed first.

There is deliberately **no tool-name table**. You already know which tools you have; look at the
capability names in `SKILL.md` and use your own equivalent. A mapping table would be stale the
moment any agent renamed a tool, and it would be read as authoritative — worse than no table.

> Adding a new agent? There is usually nothing to add here. If your agent has a quirk worth
> recording (a sandbox restriction, a missing runtime), add it under §3.

---

## 1. The capability interface

The skill needs exactly four capabilities. If your agent has them (under any name), it can run the
whole pipeline.

| Capability | What it is used for |
|---|---|
| read a file | the parsed JSON, the position CSV, previous reports |
| write a file | the fact bundle, the Markdown report, generated CSVs/HTML |
| run a shell command | the Python scripts, `git`, and (for the coordinate parser) `java` / `mvn` |
| make an HTTP request | OpenDota API calls, replay download from Valve CDN |

Optional capabilities the skill *uses if present, otherwise degrades*:

| Optional capability | Enhances | If absent |
|---|---|---|
| inline chart / diagram rendering | showing lane and distance charts in-chat | embed the chart into the report file |
| publishing a shareable link | a URL the user can open | hand back a local Markdown or HTML file |
| a background/long-running job runner | 3–10 min parse jobs | run in the foreground |

---

## 2. Token & model budgets

The point of the fact bundle is to keep the *analysis* prompt small. Scale the target to your
model's context window; when in doubt, send less and query the raw JSON on demand.

| Model / window | Suggested input per report | Notes |
|---|---|---|
| ≥ 200k (Claude 4.x, GPT-5 class) | 15–30k tokens | fact bundle + 2–4 windows is enough; don't dump combat_log |
| 100–200k (most frontier models) | 10–20k tokens | keep runs of raw JSON out of the prompt |
| 32–64k (small local / DeepSeek-class) | 6–12k tokens | minified fact bundle; one window at a time |
| ≤ 16k (tiny local models) | 3–6k tokens | do **not** run free-form forensic queries; pre-extract everything |

Rule of thumb regardless of model: **never** put a full parsed combat log (50–80 MB) in context.
The extractor's compact bundle is the contract.

---

## 3. Runtime prerequisites and sandbox gotchas

The parsers are Python (gem-dota / scripts) and Java (clarity). Install only what the path you
choose needs — see [parse-pipeline.md](parse-pipeline.md) for which path to pick.

| Need | Windows | macOS / Linux |
|---|---|---|
| Python 3.10+ | system or bundled python | `python3` |
| `gem-dota` | `pip install gem-dota` (into a venv) | same |
| Java 17+ (clarity path) | Adoptium Temurin JDK | `brew install openjdk` / apt |
| Maven (clarity path, to build once) | portable `apache-maven-*-bin.zip` (no admin needed) | `brew install maven` / apt |
| `zstd` | Python `compression.zstd` (3.14+) or `zstandard` pkg | same |

**Sandbox gotchas seen in the wild** (verify on your own agent, do not assume):

- Some sandboxes block direct downloads from `replay*.valve.net` via `urllib` while `curl` works.
  If a fetch fails with 403, retry with `curl`.
- Long no-output jobs can look "stuck" because stdout is buffered. Write progress to a log file and
  tail it, or run in the background and poll the log, not the live stream.
- Corporate/large-artifact mirrors may be **missing specific jars** (observed: an Aliyun mirror had
  the `clarity` *pom* but not the *jar*). If a build fails on a missing artifact, fetch it directly
  from Maven Central (`repo1.maven.org`) instead of the mirror.
