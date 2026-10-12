# dota2-replay-coach

English | [简体中文](README.zh-CN.md)

Provide a match ID or a `.dem` replay to automatically **download the replay → parse it → generate an evidence-backed coaching report**, then ask follow-up questions about teamfights, positioning, kills, item choices, and more.

Give your AI assistant this repository URL and ask it to install the skill in its own skills directory.

## What it does

- **Fetches data**: Uses OpenDota to retrieve match metadata and replay URLs, then downloads the original Valve replay. It can also use a `.dem` file already saved by your game client.
- **Parses the replay**: Chooses among three complementary paths based on your question: the OpenDota API without downloading a replay, full event JSON with gem-dota, or per-tick entity state with clarity. Events explain what happened; coordinates help establish where it happened.
- **Builds a queryable database**: Indexes parsed data in SQLite so the assistant can query evidence for your questions instead of relying on a fixed set of metrics.
- **Produces a report**: Starts with a verifiable Markdown draft in Chinese by default. It highlights 1–3 decisive decisions before covering the draft, game phases, teamfights, death patterns, item choices, and how advantages were converted into objectives. Publishing a shareable web page is considered after you confirm the draft.

Parsing runs entirely in code and **does not consume model tokens**. It runs once per replay; follow-up questions reuse the parsed data.

## Example questions you can ask

**The questions below are examples, not an exhaustive list.** At its core, this skill lets your AI assistant mine game logs parsed from the replay. You can ask about any aspect of your match: the assistant can write SQL queries, connect events across time, compare players and situations, and investigate follow-up questions using the same dataset.

The analysis follows your questions rather than a fixed menu of reports or predefined metrics. See [How it works](#how-it-works) below.

| Example question | Supporting evidence |
|---|---|
| Which decisions cost me this game? | Event JSON and SQL queries |
| Who dealt the damage that killed me, and what dealt it? | Damage attribution grouped by source |
| Did I use my defensive items or abilities before dying? | Item and ability activation records |
| How many Duels or ultimates connected, and how many led to wins or kills? | Ability events matched with death events |
| Did my items fit the game? Did the enemy buy detection for my invisibility? | Purchase logs and detection purchase checks |
| **How far away was my closest teammate when I died?** | Per-tick coordinates, available through the clarity path |
| Did I die alone or during a teamfight? | Spatial joins on per-tick coordinates |

The last two questions require positional evidence: **only clarity's per-tick coordinates can establish positions in this workflow**. The other questions can be answered with event data. The coordinate path requires Java and a one-time compilation; subsequent parsing takes approximately 2 seconds per match in the example setup.

## How it works

The skill turns the replay into structured game logs and entity state, then lets the AI query and connect that evidence to answer your questions. It can extend queries and extract additional replay fields when needed: clarity is a general entity reader, not just a coordinate tool. The examples above are starting points for exploring your match.

This is data analysis rather than watching replay footage. Conclusions depend on what the replay records, what the parser extracts, and the data's completeness and timing precision; the assistant should distinguish recorded facts from interpretation and flag missing evidence.

## Repository layout

```text
skills/dota2-replay-coach/
├── SKILL.md                 # Main workflow for the AI, including runnable command sequences
├── references/              # Parsing paths, SQLite schemas, data pitfalls, and fact-bundle contracts
└── scripts/                 # Downloading, indexing, fact extraction, and per-tick spatial analysis;
                             # clarity is a Java subproject
```

Detailed commands, prerequisites, troubleshooting notes, and database schemas live in the [skill documentation](skills/dota2-replay-coach/SKILL.md). The assistant reads these instructions after installation.

## Runtime and model usage

A complete data-processing run takes approximately 1–2 minutes in the example setup. Downloading, parsing, and indexing are handled by scripts and **do not consume model tokens**; report generation and follow-up answers still use the model.

Example timings are approximately 2 seconds for per-tick parsing and 3 seconds for JSON-to-SQLite indexing. Raw JSON files (50–140 MB) stay on disk; the model receives SQL query results and fact bundles of only tens of KB. Actual timings depend on the replay, download speed, and hardware.

<img width="500" alt="Example of model usage during replay analysis" src="https://github.com/user-attachments/assets/b648c9d0-62ae-4d7b-8a20-a680d46c794f" />

## Example output

The screenshots below show example reports in Chinese.

<img width="500" alt="Example coaching report, screenshot 1" src="https://github.com/user-attachments/assets/c37cb3ac-f992-49c7-b548-147c443192a5" />
<img width="500" alt="Example coaching report, screenshot 2" src="https://github.com/user-attachments/assets/c4698e11-528f-479c-a060-175f83bf9582" />
<img width="500" alt="Example coaching report, screenshot 3" src="https://github.com/user-attachments/assets/1492ca8e-e047-4002-bdef-522a85853390" />
<img width="500" alt="Example coaching report, screenshot 4" src="https://github.com/user-attachments/assets/04b676c1-a1bd-44d6-b280-0377a7f200b9" />
