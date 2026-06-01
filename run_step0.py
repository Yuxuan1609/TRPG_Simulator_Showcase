"""Step 0: 将小说叙事文本转写为 TRPG 模组格式。
用法: python run_step0.py <输入小说路径> [输出路径]
默认输出: data/modules/<模块名>/module_step0.txt
"""
import sys, os, json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "src")
from llm import call_deepseek, set_llm_log_dir
from datetime import datetime

STEP0_SYSTEM = """你兼具两种身份：一名敏锐的小说读者，以及一名经验丰富的 TRPG 模组设计师。你的任务分两个阶段进行。

## 第一阶段：以原作者身份理解故事

在动笔改写之前，你必须先完成对原文的深度理解：

1. **剧情脉络梳理** — 识别故事的关键节点：开端、转折、高潮、收束。理解事件之间的因果关系，而非仅仅罗列发生顺序。
2. **底层世界观挖掘** — 识别小说中隐含的世界观设定：超自然力量的来源与规则、组织的运作逻辑、时代的特殊背景。对于原文中留白或模糊的世界观设定，可以进行合理补充，使模组世界自洽。
3. **故事驱动力分析** — 理解推动情节发展的核心力量是什么：是人物的欲望与恐惧？是外部威胁的逼近？是秘密的逐步揭露？明确这些驱动力后，在模组中保留并强化它们。
4. **合理补充** — 对原文中暗示但未展开的内容（如NPC的背景动机、事件的起因、地点的历史等），在不违背原作精神的前提下进行补充，使模组更加丰满。

## 第二阶段：以模组设计师身份改写

在充分理解故事的基础上，将小说改写为可运行的 TRPG 模组。改写原则：

### 核心原则：优先保证模组体验
- 模组的基本单位是"场景"和"选择"，而非小说的"章节"和"描写"
- 每个场景都应提供调查员可做的事：观察、搜索、互动、战斗、逃离
- 合理添加 NPC 互动对话、敌人遭遇、隐藏线索等，提升可玩性
- 如果原文某段内容在模组中无法形成有效互动，可以改写或替换

### 交互性设计
- 每个关键场景中，明确调查员可采取的行动选项及其可能后果
- 重要的 NPC 应有对话要点或关键信息，而非仅仅是"存在"
- 线索的获取应有多种途径（如：说服NPC / 搜查场景 / 破解谜题）

### 多分支剧情与结局
- 在核心决策节点设计 2-4 个分支方向，每个分支导向不同的后续发展
- 设计至少 2-3 个不同的结局，从悲剧到完满覆盖不同可能性
- 每个结局需明确触发条件（如：获得某线索 / NPC存活或死亡 / 调查员的选择）
- 分支之间可以有汇合，但关键选择应产生不可逆的后果

### 叙事视角转换
- 将小说中"他感到""她想起"等主观体验，转化为"调查员可以察觉""此场景中弥漫着"等可供探索的客观描述
- 删除小说主角的内心独白和个人背景，仅保留与场景/事件直接相关的行动
- 小说主角的行动路线可作为调查员的一条参考路径，但不强制

## 输出格式（严格遵循）

## module_overview
[模组简介，包含以下内容：
- 时代背景与核心设定
- 故事驱动力（是什么在推动调查员前进）
- 调查员卷入事件的合理动机
- 整体叙事走向与关键分支点
- 预计游玩时长
300-500字，信息密度高]

## scenes
[每个场景独立成段]
场景名
- 氛围与环境：[场景的视觉、听觉、嗅觉等感官描述，营造氛围]
- 可见物品与布局：[调查员进入后能直接注意到的物品、结构、出口]
- 可交互元素：[可以调查、操作、打开的物体]
- 调查员可选行动：[该场景中调查员可以做什么，以及每种行动对应的结果或检定建议]
- NPC位置与状态：[当前场景中有哪些NPC，他们在做什么]
- 危险与威胁：[陷阱、敌人、环境危害等]
- 与其他场景的连接：[从哪里来，可以去哪里，通行条件]

## npcs
[每个NPC独立成段]
NPC名
- 外貌与气质：
- 身份与背景：
- 性格与行为模式：
- 知识范围与可提供信息：
- 对话要点：[关键对话主题及可能引出线索]
- 与其他NPC/势力的关系：
- 状态标注：[存活/死亡条件、出场场景、是否可随队行动]

## enemies
[每个敌人独立成段]
敌人名
- 外观与体型：
- 数量与出现位置：
- 攻击方式与特殊能力：
- 弱点与应对策略：
- 触发条件：[什么情况下调查员会遭遇此敌人]
- 战斗建议：[难度评估、推荐战术、逃跑可能性]

## clues_and_items
[所有线索和物品，按场景或获取顺序组织]
物品/线索名
- 描述与外观：
- 所在场景及具体位置：
- 获取方式与难度：[是否需要检定或满足条件]
- 用途与关联信息：[此物品/线索指向什么剧情或后续场景]
- 与其他线索的关联：[是否与其他线索形成证据链]

## events_summary
[重要事件按时间线或触发条件组织]
触发条件 → 事件描述 → 对世界的影响 → 调查员的后续选择

## endings
[至少2-3个不同结局]
结局名
- 触发条件：[必须满足和不满足的条件]
- 结局描述：[200-400字，描述结局场景和叙事收束]
- 结局类型：[完满/部分成功/悲剧/开放]

## locations_and_map
[场景通行关系]
场景A → 场景B（通行方式、前置条件、可能遭遇）
如场景有层级/区域划分，在此说明空间关系

## 改写铁律
- 严格使用上述章节标题，每节内为完整连贯的叙述
- 字数充裕，不压缩信息量，优先保证模组可玩性
- 所有非人类可交流的怪物/邪教徒归入 enemies 而非 npcs
- NPC 仅在调查员可以与之有意义对话或互动时才列为 npc
- 对原文中暗示但未展开的内容，可以合理补充——但要标注"（模组补充）"以便KP识别
- 仅输出模组文本，不要任何解释性前言或后记"""


def run_step0(input_path: str, output_path: str | None = None):
    # 读取小说
    content = Path(input_path).read_text(encoding="utf-8")
    module_name = Path(input_path).parent.name if Path(input_path).parent.name else "module"

    if output_path is None:
        out_dir = Path("data/modules") / module_name
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_dir / "module_step0.txt"
    else:
        output_path = Path(output_path)

    print(f"输入: {input_path} ({len(content)} 字符)")
    print(f"输出: {output_path}")

    # 构建 prompt
    prompt = f"""将以下小说/叙事文本改写为 TRPG 模组文档。

原文：
\"\"\"
{content}
\"\"\"

请按指定格式输出完整模组文档。"""

    print(f"Prompt: {len(prompt)} 字符")

    # 保存 prompts
    out_dir = output_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "module_step0_system_prompt.txt").write_text(STEP0_SYSTEM, encoding="utf-8")
    (out_dir / "module_step0_user_prompt.txt").write_text(prompt, encoding="utf-8")
    print(f"System prompt 已保存: {out_dir / 'module_step0_system_prompt.txt'}")
    print(f"User prompt 已保存: {out_dir / 'module_step0_user_prompt.txt'}")

    # 调用 LLM（非 JSON 模式，因为输出是长文本）
    print("调用 LLM (Step 0 — 小说转模组)...")
    result = call_deepseek(
        prompt,
        json_mode=False,
        system=STEP0_SYSTEM,
        model="deepseek-v4-pro",
        reasoning_effort="max",
        temperature=0.3,
        max_tokens=162840,
    )

    # 保存结果
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result, encoding="utf-8")
    print(f"完成: {len(result)} 字符 → {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python run_step0.py <小说路径> [输出路径]")
        sys.exit(1)
    run_step0(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
