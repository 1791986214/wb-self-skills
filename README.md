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
| 02 | **逐帧二创增量冻结交付** | `pv-incremental-frozen-delivery` | 「逐帧二创视频」的多轮返修交付范式——冻结上一版做底层，只改目标帧，范围外逐字节校验，增量打包 + 用户交付目录 + 如实验收。触发词：PV 返修、视频返修、增量渲染、冻结上一版、V8/V9 交付、逐帧二创、范围外逐字节、素材包、交付目录、帧号定位。适用项目：/Users/lang/Documents/Codex/20… | 4 KB | 2026-10-05 |
| 03 | **项目架构归一化框架图** | `archinorm` | 项目框架·归一化框架图构建器。把项目架构写成归一化的分形模块树，并渲染成深色交互式架构图（节点链路图 + 依赖曲线 + 语义着色 + 下钻面板）。触发词：架构图、框架图、结构图、模块树、项目结构、画架构、代码地图、archinorm、归一化、迁移项目、给项目建结构。凡涉及代码的项目在设计或开发阶段应默认套用本框架。 | 486 KB | 2026-10-13 |
| 04 | **项目地图** | `project-map-skill` | 【v1.2.2】项目地图——把「项目计划 / 项目指令 / 项目资产 / 项目记忆」等口头术语映射到具体载体与工具；收工自动做「记忆双写 + 资产同步」 | 12 KB | 2026-10-13 |

> 共 **4** 个技能，合计 **507 KB**；清单刷新时间 2026-10-13 17:29:07。
<!-- SKILLS-TABLE:END -->

---

## 怎么用（三个动作）

### 1. 装到新机器

1. 从 `skills/` 里下载需要的 zip
2. 解压，得到 `技能目录名/`（例如 `archinorm/`）
3. 把整个目录放进 `~/.workbuddy/skills/`
4. 开个新会话，技能就生效了

> 目录名别改 —— WorkBuddy 靠目录名和 `SKILL.md` 里的 `name` 认技能。
> 中文名只在 zip 文件名和本页表格里，属于「备注」，改不了识别。

### 2. 日常更新（技能改了之后）

在 WorkBuddy 会话里直接跟小乐说：

> **同步技能到 git**

或者手动跑：

```bash
cd <本仓库目录>
python3 sync_skills.py --push "这次改了什么"
```

脚本会重新打包名单里的技能 → 刷新 `manifest.json` 和本页表格 → 提交推送。

### 3. 增删技能（维护名单）

名单在 `roster.json`，**只放高频的**。

```bash
python3 sync_skills.py --usage                 # 先看频率排行，决定收谁
python3 sync_skills.py --list                  # 看当前收了哪些
python3 sync_skills.py --add mac-settings-cli  # 收一个进来（中文名自动取）
python3 sync_skills.py --remove archinorm      # 剔一个出去
python3 sync_skills.py --push "调整名单"        # 重新打包 + 上传
```

剔掉的技能，它的 zip 会自动从仓库里清掉。

---

## 频率排行怎么来的

用技能市场装的 **skill-meter（技能使用统计）**：

- 计数库：`~/.workbuddy/skill_usage.db`
- 看 TOP：`python3 ~/.workbuddy/skills/skill-meter/scripts/track.py top 20 --since all`
- 看从没被调过的：`... track.py unused`
- 本仓库封装：`python3 sync_skills.py --usage`

> ⚠️ 次数统计靠 `~/.workbuddy/settings.json` 里的 `PostToolUse` hook 自动记（跑
> `skill-meter/scripts/install_hook.py` 装）。**没装 hook 就只有历史空数据**，
> 装之前可以考虑用 `backfill_from_transcripts.py` 从会话记录回填。
> 装 hook 的代价是每次技能调用多起一个进程，介意会话卡顿的话先别装。

---

## 文件说明

| 文件 | 作用 |
|---|---|
| `skills/*.zip` | 技能包，中文文件名 |
| `roster.json` | 收录名单（中文名 + 目录名），维护就改这里 |
| `manifest.json` | 机器可读清单：说明 / 触发词 / 体积 / sha256 / 更新时间 |
| `sync_skills.py` | 打包 + 刷新清单 + 推送，一条命令搞定 |
| `README.md` | 就是本页，清单表由脚本自动填 |

---

## 说明

- 本仓库只收**自制技能**；技能市场装的第三方技能不入库（直接重装即可）。
- 打包排除 `.state/`、`__pycache__/`、`.DS_Store` 这类运行时垃圾。
- 目前未收录的本地自制技能（按需 `--add` 收进来即可）：
  `mac-shell-env-setup`、`mac-settings-cli`、`mac-device-info-doc`、
  `api-key-endpoint-verify`、`workbuddy-local-fault-diagnose`。
