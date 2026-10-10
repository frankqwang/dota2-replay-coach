# Agent adapters — the only place agent- and model-specific details live

`SKILL.md` is deliberately tool-agnostic: it only names **capabilities**. This file maps those
capabilities to real tools, budgets, and platform quirks for specific agents/models. If you are an
agent running this skill, read this file once, resolve the mapping for *yourself*, and then forget
the tool names — do the analysis in capability terms.

> Adding a new agent? Append a row to the tables below; do not touch `SKILL.md`.

---

## 1. The capability interface

The skill needs exactly four capabilities. If your agent has them (under any name), it can run the
whole pipeline.

| Capability | What it is used for |
|---|---|
| `read_file` | read parsed JSON, position CSV, previous reports, `hero_cn.json` / `items_id.json` |
| `write_file` | write the fact bundle, the Markdown report, generated CSVs/HTML |
| `run_shell` | run the Python scripts, `git`, and (for the coordinate parser) `java` / `mvn` |
| `http_fetch` | OpenDota API calls, replay download from Valve CDN |

Optional capabilities the skill *uses if present, otherwise degrades*:

| Optional capability | Enhances | Degrades to |
|---|---|---|
| inline visualizer (chart/diagram) | showing lane/distance charts in-chat | embed a chart into the report file |
| static-site / artifact publishing | shareable link | a local Markdown or HTML file |
| background/long-running task runner | 3–10 min parse jobs | run in foreground |

---

## 2. Tool-name mapping

| Capability | WorkBuddy | Claude Code | Cursor / Windsurf | Codex CLI | Generic bash agent |
|---|---|---|---|---|---|
| `read_file` | `Read` | `Read` | `Read` | shell `cat`/`sed` | `cat` |
| `write_file` | `Write` / `Edit` | `Write` / `Edit` | `Write` / `Edit` | shell heredoc | `cat >` |
| `run_shell` | `Bash` (Git Bash) / `PowerShell` | `Bash` | `Bash` | its sandbox shell | `bash` |
| `http_fetch` | `WebFetch` / `WebSearch` | `WebFetch` | `WebFetch` | `curl` | `curl` |
| background job | `Bash` with `run_in_background` + `TaskOutput` | `Bash` `&` + `wait` | terminal | `&` | `nohup … &` |
| inline visual | `show_widget` (SVG/HTML) | Artifact | preview | — | — |
| share / publish | `present_files` (+ optional Sites deploy) | Artifact link | — | — | local file |

If your agent is not listed: you need file read/write, a shell, and HTTP. That is sufficient.

---

## 3. Token & model budgets

The point of the fact bundle is to keep the *analysis* prompt small. Adjust the target to your
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

## 4. Runtime prerequisites (per OS)

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

---

## 5. Publishing / sharing matrix

The skill produces Markdown first (fast to verify). "Share" is then whatever your agent supports:

| Agent | Recommended share path |
|---|---|
| WorkBuddy | `present_files` to show the report; optionally deploy a validated static package as a hosted site |
| Claude Code | an Artifact, or write a self-contained `report.html` |
| Cursor / Windsurf | open the HTML in the editor preview |
| Codex CLI / generic | leave a local `report.html` / `.md`; tell the user the path |

Encoding gate is universal and lives in `SKILL.md` (UTF-8 end to end for any HTML/JSON).

---

## 6. Worked example — the reference environment this skill was built on

This is **one** concrete setup, included so you can copy the shape, not as a requirement:

- Agent: WorkBuddy on Windows 11; shell is Git Bash; a sandboxed bash plus a `PowerShell` tool.
- Python for parsing: a dedicated venv, e.g. `…/python/envs/dota/Scripts/python.exe`.
- Java: Temurin JDK 21 at `C:/Program Files/Eclipse Adoptium/jdk-21.0.11.10-hotspot`.
- Maven: portable 3.9.9 unpacked under the project's `tools/`, with a `settings.xml` pointing at a
  regional mirror for speed (and manual `repo1.maven.org` fetches for the two jars the mirror lacked).
- Publish: `present_files` for the report; coordinate parser output kept as a CSV artifact.

Translate to your own paths; none of the above is load-bearing for the *method*.
