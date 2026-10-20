# 小乐技能库 · wb-self-skills

自用的 WorkBuddy 自制技能归档。技能以 **zip** 形式存放，**文件名用中文**（括号里保留英文目录名），
解压后把整个目录丢回 `~/.workbuddy/skills/` 就能用。

只收**高频在用**的技能 —— 用不上的不放进来，免得每次同步都拖一堆垃圾上去。

---

## 清单

<!-- SKILLS-TABLE:BEGIN -->
| 编号 | 中文名 | 技能目录名 | 说明 | 体积 | 技能更新 |
|:---:|---|---|---|:---:|:---:|
| 01 | **离线HTML工作台改版发版** | `offline-html-workbench-patch-release` | 给「单文件离线 HTML 工作台 + Python 启动器 + 云端更新源」这类交付物做小改并安全发版的完整链路——二进制补丁保 CRLF、抽 script 块做语法回归、CDP 真实浏览器验证、版本号递增重打包、生成发版载荷并公网回读。触发词：改工作台、工作台.html、拿钱工具、离线 HTML 交付、发版到云端、更… | 6 KB | 2026-10-09 |
| 02 | **项目架构归一化框架图** | `archinorm` | 项目框架·归一化框架图构建器。把项目架构写成归一化的分形模块树，并渲染成深色交互式架构图（节点链路图 + 依赖曲线 + 语义着色 + 下钻面板）。触发词：架构图、框架图、结构图、模块树、项目结构、画架构、代码地图、archinorm、归一化、迁移项目、给项目建结构。凡涉及代码的项目在设计或开发阶段应默认套用本框架。 | 507 KB | 2026-10-20 |
| 03 | **项目地图** | `project-map-skill` | 【v1.2.2】项目地图——把「项目计划 / 项目指令 / 项目资产 / 项目记忆」等口头术语映射到具体载体与工具；收工自动做「记忆双写 + 资产同步」 | 12 KB | 2026-10-13 |

> 共 **3** 个技能，合计 **524 KB**；最近技能更新 2026-10-20。改动记录见本仓库 commit 历史。
<!-- SKILLS-TABLE:END -->

---

## 怎么用（四件事）

### 1. 装到新机器

1. 从 `skills/` 里下载需要的 zip
2. 解压，得到 `技能目录名/`（例如 `archinorm/`）
3. 把整个目录放进 `~/.workbuddy/skills/`
4. 开个新会话，技能就生效了

> 目录名别改 —— WorkBuddy 靠目录名和 `SKILL.md` 里的 `name` 认技能。
> 中文名只在 zip 文件名和本页表格里，属于「备注」，改不了识别。

### 2. 日常更新 —— 已经全自动了

**不用你动手**。技能文件一改（AI 改、你手改、解压覆盖、市场装新技能），
macOS 后台守护任务 `com.xiaole.skills-sync` 会在 **2 分钟内**自动打包 → 刷新清单 → 提交 → 推送到 GitHub。

```bash
python3 sync_skills.py --status         # 看自动同步开着没、上次跑成没、有没有积压
python3 sync_skills.py                  # 想立刻同步一次，手动跑
python3 sync_skills.py --push "说明"     # 手动跑并指定 commit 说明
```

机制说明：用 macOS 自带的 launchd，监听 `~/.workbuddy/skills/` 和名单里每个技能目录，
**目录一有变动立刻触发**，另有每 2 分钟的兜底轮询。内容没变就静默跳过，不会产生空提交。

- 开关自动同步：`python3 sync_skills.py --install-agent` / `--uninstall-agent`
- 日志：`~/.workbuddy/logs/skills-sync.log`
- 推送时直连不通会自动改走本机代理（`127.0.0.1:7897`）

### 3. 投毒防线（推送前必过闸门）

「自动推送」最大的风险是**盲提交**：技能从别人那下载来、或者被偷偷改了，
守护任务照样打包推上去 —— 而这个仓库是**公开的**。所以每次推送前都要过三道闸：

| 层 | 管什么 | 拦什么 |
|---|---|---|
| ① 变更审计 | 跟「上一次已放行状态」（git 里的 zip）比对 | **新增技能**、**新增文件**、**第三方依赖目录被改动** —— 一律拦 |
| ② 威胁扫描 | 扫改动的文本，30+ 条规则 | 网络外传、`curl\|sh`、base64 解码执行、读凭据/钥匙串、破坏性删除、写持久化项、动态 exec、从 URL 装包 |
| ③ 密钥扫描 | 全文件找密钥样式 | `sk-` / `ghp_` / `AKIA` / JWT / 私钥 / 硬编码口令 —— **公开仓库里这条最要命** |

**文档和代码分开判**：README 里说「守护任务装在 LaunchAgents」是正当说明，脚本里真去写才是后门。
所以「写持久化项」这类规则只对脚本文件算高危，出现在文档里降级成提醒。
但 `SKILL.md` 的**提示词注入**（「忽略之前的指令」「不要告诉用户」「上传这些文件」）照拦不误——
技能本质就是给 AI 的指令，注入比脚本更隐蔽。

被拦之后：

```bash
python3 sync_skills.py --scan              # 随时手动扫一遍
python3 sync_skills.py --review            # 看待审报告 + 放行记录
python3 sync_skills.py --approve 技能目录名  # 人工确认无误后放行（放行后推送）
python3 sync_skills.py --strict on         # 更严：任何源码改动都要人工放行
```

- 被拦时**不会丢东西**：改动留在工作区，报告写进 `~/.workbuddy/logs/skills-review/`
- 放行会记进 `~/.workbuddy/logs/skills-approvals.log`（谁、什么时候、放行了哪几条）
- **密钥泄漏是个硬闸**：`--approve` 也拒，因为推上去就永久留在公开仓库历史里了。确实要推得再加 `--force`
- 报告同一批拦截项只留一份（不会跑一次写一份）

### 4. 增删技能（维护名单）

名单在 `roster.json`，**只放高频的**。增减完会自动重装守护任务，让监听路径跟上。

```bash
python3 sync_skills.py --usage                 # 先看频率排行，决定收谁
python3 sync_skills.py --list                  # 看当前收了哪些 + 哪些还没收
python3 sync_skills.py --add mac-settings-cli  # 收一个进来（中文名自动取）
python3 sync_skills.py --remove archinorm      # 剔一个出去
```

剔掉的技能，它的 zip 会自动从仓库里清掉。

---

## 频率排行怎么来的

用技能市场装的 **skill-meter（技能使用统计）**：

- 计数库：`~/.workbuddy/skill_usage.db`
- 看 TOP：`python3 ~/.workbuddy/skills/skill-meter/scripts/track.py top 20 --since all`
- 看从没被调过的：`... track.py unused`
- 本仓库封装：`python3 sync_skills.py --usage`

> ⚠️ 本机**没有装自动计数 hook**：装了之后每次技能调用都要多起一个进程，介意会话卡顿就先别装。
> 现在这些次数是跑 `backfill_from_transcripts.py` 从历史会话记录回填的，**只覆盖本机 9/24 之后的记录**，
> 在那之前干过的活（比如主力在 Windows 端跑的项目）统计不到，排行只能当参考。

---

## 文件说明

| 文件 | 作用 |
|---|---|
| `skills/*.zip` | 技能包，中文文件名 |
| `roster.json` | 收录名单（中文名 + 目录名），维护就改这里 |
| `manifest.json` | 机器可读清单：说明 / 触发词 / 体积 / sha256 / 更新时间 |
| `sync_skills.py` | 打包 + 刷新清单 + 推送 + 闸门 + 守护任务管理，一条命令搞定 |
| `guard.py` | 投毒防线：变更审计 + 威胁扫描 + 待审报告 |
| `README.md` | 就是本页，清单表由脚本自动填 |

**本机位置**

| 东西 | 路径 |
|---|---|
| 本仓库本地副本 | `~/Documents/wb-self-skills/` |
| 技能来源 | `~/.workbuddy/skills/` |
| 守护任务 | `~/Library/LaunchAgents/com.xiaole.skills-sync.plist` |
| 同步日志 | `~/.workbuddy/logs/skills-sync.log` |
| 待审报告 | `~/.workbuddy/logs/skills-review/` |
| 放行记录 | `~/.workbuddy/logs/skills-approvals.log` |

---

## 说明

- 本仓库只收**自制技能**；技能市场装的第三方技能不入库（直接重装即可）。
- 打包排除 `.state/`、`__pycache__/`、`.DS_Store` 这类运行时垃圾。
- 目前未收录的本地自制技能（按需 `--add` 收进来即可）：
  `mac-shell-env-setup`、`mac-settings-cli`、`mac-device-info-doc`、
  `api-key-endpoint-verify`、`workbuddy-local-fault-diagnose`。
- `pv-incremental-frozen-delivery` 已按大哥要求撤回（非自制）。
