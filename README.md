# dota2-replay-coach

一个 **agent 无关**的 Dota 2 复盘 skill：给它一个比赛 ID（或 `.dem` 录像），它自动完成
**下载录像 → 解析 → 生成可核对的教练报告**，然后回答你关心的任何问题（团战、走位、击杀、出装……）。

## 为什么叫 "agent 无关"

`SKILL.md` 里**不出现任何具体工具名**，只声明它需要的 4 项能力：读文件、写文件、跑命令、发 HTTP 请求。
不同 agent / 模型之间的差异（工具名、token 预算、沙箱限制、发布方式、运行环境）**全部集中在单独一份文档**：

> [`skills/dota2-replay-coach/references/agent-adapters.md`](skills/dota2-replay-coach/references/agent-adapters.md)

这样同一份 skill 可以跑在 WorkBuddy / Claude Code / Cursor / Codex CLI 或任何有 shell 的 agent 上，
新增一个 agent 只需要在那份文档里**加一行表格**，不用动主流程。

## 安装

把仓库地址丢给你的 AI，让它安装这个 skill；或手动把 `skills/dota2-replay-coach/` 放到你的 skill 目录：

| Agent | 默认 skill 目录 |
|---|---|
| WorkBuddy | `~/.workbuddy/skills/` |
| Claude Code | `~/.claude/skills/` |
| 其他 / 通用 | 把 `SKILL.md` 与 `references/`、`scripts/` 放在一起，让 agent 读取即可 |

## 它做什么

1. **取数据**：根据比赛 ID 从 OpenDota 拿元数据与录像下载链接，下载 Valve 原始录像（或直接用客户端本地已有的 `.dem`）。
2. **解析**（三条路径，按问题选）：
   - **OpenDota API** — 免下载，分钟级聚合数据，适合快速过一遍；
   - **gem-dota** — 全量游戏事件 JSON（团战、技能、购买、伤害归因），适合事件级取证；
   - **clarity（Java，与 OpenDota 同款解析库）** — **逐 tick 英雄坐标**（每 0.5 秒 × 10 人），
     这是最独特的一路：它能回答 "我死的那一刻，最近的队友离我多远" 这类**只有坐标才能证明**的问题。
3. **出报告**：默认先给一份可核对的中文 Markdown 草稿（先讲 1–3 个胜负手，再展开 BP / 分阶段 /
   团战 / 死亡归类 / 出装 / 转化），确认后再考虑分享成网页。

解析是程序完成的，**不吃模型 token**；一次性动作，后续追问不会重复解析。

## 目录结构

```
skills/dota2-replay-coach/
├── SKILL.md                       # 主流程（agent 无关，只谈能力不谈工具名）
├── references/
│   ├── agent-adapters.md          # ★ agent/模型差异（工具映射、token 预算、发布方式、环境）
│   ├── parse-pipeline.md          # 三条解析路径的完整操作与坑
│   ├── data-traps.md              # 数据陷阱与取证配方（读任何指标前必看）
│   └── data-contract.md           # 事实包（fact bundle）的字段契约
└── scripts/
    ├── fetch_replay.py            # 下载 + 解压录像（按魔数识别 zstd/bzip2）
    ├── query_parsed.py            # 定向查询（players / kills / items / nw）
    ├── extract_match_facts.py     # 抽取精简事实包（给模型看的）
    ├── ticks_report.py            # 逐 tick 坐标 -> 英雄/队伍/轨迹
    ├── ticks_deep.py              # 逐 tick 坐标 -> 对线对手 + 死亡态势 + 死亡前轨迹
    └── clarity/                   # ★ 逐 tick 坐标解析器（Java，Maven 工程）
        ├── pom.xml
        └── ReplayDump.java
```

## 快速开始（逐 tick 坐标解析器）

```bash
cd skills/dota2-replay-coach/scripts/clarity
mvn -B -DskipTests package          # 依赖 com.skadistats:clarity:5.0.1（Maven Central）
java -Xmx3g -jar target/dota-lc-parse.jar <replay.dem> <out.csv> 15
```

输出：`gametime,tick,index,dtname,team,heroid,x,y,hp,maxhp,level,lifestate`（每约 0.5 秒一行）。
注意 `gametime` 是原始 `tick/30`，需要按死亡时刻对齐校准后再用——详见 `parse-pipeline.md`。

## 关于成本

- 录像下载 + 解析全部由脚本完成，**无模型成本**；时间约 1–2 分钟（jar 已构建后，逐 tick 解析仅约 2 秒）。
- 默认只把精简事实包（几十 KB）喂给模型，原始 JSON 留在磁盘上按需查询。
- 粗略成本如下图：

<img width="500" alt="475650e2a6373173aba6f36b9a7903e5" src="https://github.com/user-attachments/assets/b648c9d0-62ae-4d7b-8a20-a680d46c794f" />

## 效果示例

<img width="500" alt="aa95edefdbe41ae16fec15c9c61ad1dc" src="https://github.com/user-attachments/assets/c37cb3ac-f992-49c7-b548-147c443192a5" />
<img width="500" alt="832887e041eacc1d6040afdecb02f335" src="https://github.com/user-attachments/assets/c4698e11-528f-479c-a060-175f83bf9582" />
<img width="500" alt="8e6216e11b1fc88958f498f486302059" src="https://github.com/user-attachments/assets/1492ca8e-e047-4002-bdef-522a85853390" />
<img width="500" alt="f1575479596b5e742ad00e350977003b" src="https://github.com/user-attachments/assets/04b676c1-a1bd-44d6-b280-0377a7f200b9" />
