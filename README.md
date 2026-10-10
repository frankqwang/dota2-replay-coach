# dota2-replay-coach

给一个比赛 ID（或 `.dem` 录像），自动完成**下载录像 → 解析 → 生成可核对的教练报告**，
然后回答你关心的任何问题（团战、走位、击杀、出装……）。

适用于任何支持 skill 的 AI 编程助手，不绑定特定工具。

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
   - **clarity（Java，与 OpenDota 同款解析库）** — 读整份实体图，可按需导出**任意实体字段**。
     仓库里自带的 dump 类输出的是**逐 tick 英雄坐标**（每 0.5 秒 × 10 人），这是三条路径里
     唯一能回答 "我死的那一刻，最近的队友离我多远" 这类**只有坐标才能证明**的问题的数据。

     注意：一场 46 分钟的比赛有 **466 个实体类**（10 个英雄、168 个技能、227 个物品，每队
     6288 个统计字段……），坐标只是其中一个类的输出。需要别的字段就先探测：
     `scripts/clarity/Survey.java`。
3. **建索引**：把解析出的 JSON 转成 SQLite，之后由 AI 直接写 SQL 查询，**自由度更大**，
   不再受限于固定脚本能吐出的那几个指标。
4. **出报告**：默认先给一份可核对的中文 Markdown 草稿（先讲 1–3 个胜负手，再展开 BP / 分阶段 /
   团战 / 死亡归类 / 出装 / 转化），确认后再考虑分享成网页。

解析是程序完成的，**不吃模型 token**；一次性动作，后续追问不会重复解析。

## 快速上手

最常用的路径——给一个比赛 ID，出报告：

```bash
# 0) 装 gem-dota（只需一次，建议独立 venv）
python -m venv .venv && . .venv/bin/activate && pip install gem-dota

# 1) 下载 + 解压录像（已有 .dem 就跳过）
python skills/dota2-replay-coach/scripts/fetch_replay.py 9036564967 ./work

# 2) 解析成完整事件 JSON（约 1–3 分钟，gem-dota）
python -m gem parse ./work/9036564967.dem --format json \
    --output ./work/parsed_9036564967.json --no-banner

# 3) 建 SQLite 索引（约 3 秒），之后用 SQL 自由查
python skills/dota2-replay-coach/scripts/index_parsed.py ./work/parsed_9036564967.json --info

# 4) 或直接生成一份给模型看的精简事实包
python skills/dota2-replay-coach/scripts/extract_match_facts.py \
    --parsed ./work/parsed_9036564967.json \
    --hero legion_commander --out ./work/facts_9036564967.json
```

第 3 步之后用 SQL 取数（表结构见 [`references/parsed-schema.md`](skills/dota2-replay-coach/references/parsed-schema.md)）：

```bash
sqlite3 ./work/parsed_9036564967.db \
  "SELECT hero_name, net_worth, last_hits FROM players ORDER BY net_worth DESC"
```

把 `facts_*.json`（几十 KB）或 SQL 查询结果交给 AI，它就能出报告。需要"死亡时队友离我多远"
这类只有坐标才能证明的问题时，再走下面的逐 tick 路径。

更完整的路径选择、前置依赖与踩坑见
[`references/parse-pipeline.md`](skills/dota2-replay-coach/references/parse-pipeline.md)。

## 目录结构

```
skills/dota2-replay-coach/
├── SKILL.md                       # 主流程
├── references/
│   ├── parse-pipeline.md          # 三条解析路径的完整操作、前置依赖与坑
│   ├── parsed-schema.md           # ★ 解析数据的 SQLite 表结构 + 示例查询（问数据前先看）
│   ├── data-traps.md              # 数据陷阱与取证配方（读任何指标前必看）
│   └── data-contract.md           # 事实包（fact bundle）的字段契约
└── scripts/
    ├── fetch_replay.py            # 下载 + 解压录像（按魔数识别 zstd/bzip2）
    ├── index_parsed.py            # ★ 解析 JSON → SQLite，之后随便写 SQL 查
    ├── extract_match_facts.py     # 抽取精简事实包（给模型看的）
    ├── ticks_coach.py             # ★ 逐 tick 态势分析：时钟校准 + 每次死亡时谁在附近
    └── clarity/                   # ★ clarity 解析器（Java，Maven 工程）
        ├── pom.xml
        ├── ReplayDump.java        # 逐 tick 英雄坐标 CSV
        └── Survey.java            # 探查：这把录像里有哪些实体类 / 字段
```

## 数据怎么查

**核心原则：解析出来的完整事件数据（一场 40 分钟约 50–140 MB，约 15–33M token）不喂给模型。**

先把它建成 SQLite 库（上面快速上手第 3 步），之后由 AI 直接写 SQL 取数——这样它能按你的
问题自由取数，而不是只能拿到几个写死的指标。表结构与示例 SQL（找凶手、决斗台账、经济窗口、
死亡时最近队友距离）见 [`references/parsed-schema.md`](skills/dota2-replay-coach/references/parsed-schema.md)。

有两个细节值得注意：

- **所有时间列已统一为游戏内秒数（已扣除暂停）**，与计分板直接对齐。负值 = 赛前购物期。
- 原始 JSON 与 `.dem` 都留在磁盘上，`.db` 是可随时重建的派生物（已加 `.gitignore`）。

## 逐 tick 坐标分析（clarity 路径）

三条解析路径里，只有这一条能回答"**我死的那一刻，最近的队友离我多远**"——因为只有它有逐 tick 坐标。
下面的命令都假设你**在仓库根目录**，产物放在 `work/`。

**1) 先建解析器**（一次性；之后解析一把录像约 2 秒）

```bash
cd skills/dota2-replay-coach/scripts/clarity
mvn -B -DskipTests package          # 依赖 com.skadistats:clarity:5.0.1（Maven Central）
cd -                                # 回到仓库根目录
```

产物是 `skills/dota2-replay-coach/scripts/clarity/target/dota-lc-parse.jar`。
没有 Maven 也可以直接对已构建的 jar 编译单个类（见 `references/parse-pipeline.md`）。

**2) 导出逐 tick 坐标 CSV**

```bash
JAR=skills/dota2-replay-coach/scripts/clarity/target/dota-lc-parse.jar
java -Xmx3g -jar $JAR work/9036564967.dem work/ticks_9036564967.csv 15
```

输出 `gametime,tick,index,dtname,team,heroid,x,y,hp,maxhp,level,lifestate`（每约 0.5 秒一行）。
**`gametime` 是原始 `tick/30`，含暂停、含赛前时间，必须先校准**（下一步）。

**3) 分析与校准**

```bash
CSV=work/ticks_9036564967.csv

# 看这把有哪些英雄
python skills/dota2-replay-coach/scripts/ticks_coach.py $CSV --list-heroes

# 校准时钟 + 逐次死亡态势（传入计分板/OpenDota 的真实死亡时刻）
python skills/dota2-replay-coach/scripts/ticks_coach.py $CSV \
    --me legion_commander --death-times 87,1085,1972

# 或直接给定偏移量跳过校准（偏移量是每场独立的，换局必须重算）
python skills/dota2-replay-coach/scripts/ticks_coach.py $CSV \
    --me legion_commander --offset 229
```

`ticks_coach.py` 会自动识别这把的英雄与阵营、把幻象归到本体、用**中位数**求解时钟偏移
（单次死亡时刻记错不会污染整局），并对每次死亡给出「团战 / 迟到支援 / 落单」的判定。
**校准不上时它会拒绝输出派生时间**，而不是给出不可信的数字——如果看到 `✗ offset NOT
trustworthy`，说明传入的死亡时刻有问题，去核对而不是继续用。

## 关于成本

- 录像下载、解析、建索引全部由脚本完成，**无模型成本**；一次完整流程约 1–2 分钟
  （jar 已构建后，逐 tick 解析约 2 秒，JSON→SQLite 约 3 秒）。
- 原始 JSON（50–140 MB）留在磁盘上，模型只拿 SQL 查询结果和精简事实包（几十 KB）。
- 粗略成本如下图：

<img width="500" alt="475650e2a6373173aba6f36b9a7903e5" src="https://github.com/user-attachments/assets/b648c9d0-62ae-4d7b-8a20-a680d46c794f" />

## 效果示例

<img width="500" alt="aa95edefdbe41ae16fec15c9c61ad1dc" src="https://github.com/user-attachments/assets/c37cb3ac-f992-49c7-b548-147c443192a5" />
<img width="500" alt="832887e041eacc1d6040afdecb02f335" src="https://github.com/user-attachments/assets/c4698e11-528f-479c-a060-175f83bf9582" />
<img width="500" alt="8e6216e11b1fc88958f498f486302059" src="https://github.com/user-attachments/assets/1492ca8e-e047-4002-bdef-522a85853390" />
<img width="500" alt="f1575479596b5e742ad00e350977003b" src="https://github.com/user-attachments/assets/04b676c1-a1bd-44d6-b280-0377a7f200b9" />
