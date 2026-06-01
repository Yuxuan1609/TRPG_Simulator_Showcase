# Test Suites — 测试体系

日期：2026-05-20
状态：3 套测试，19 个用例，覆盖游戏循环全链路 + Author 介入机制

## 总览

| 套件 | 文件 | 用例数 | LLM 调用 | 日志输出 |
|------|------|--------|----------|----------|
| Game Loop Harness | `tests/game_loop_harness.py` | 7 轮 | 真实 (40-50 次) | `data/debug/test_harness/<ts>/` |
| Author Flow 单元测试 | `tests/test_author_flow.py` + `tests/test_intent_detector.py` | 11 个 | 全 mock | 无（纯逻辑验证） |
| Escalation Harness | `tests/test_escalation_harness.py` | 5 个 case | 全 mock | `data/debug/test_escalation/<ts>/` |

---

## 1. Game Loop Harness (`tests/game_loop_harness.py`)

真实 LLM 调用的串行多轮集成测试。覆盖：

```
Turn 1: search — 侦查检定 + trait enhancement
Turn 2: interact IT3 — 无检定交互（观察镜子）
Turn 3: interact IT1 — 侦查检定 + ##GRADED##
Turn 4: interact IT2 — 图书馆使用检定，依赖 IT1
Turn 5: interact IT4 — 力量检定 (hard)
Turn 6: move — 移动到 6 号车厢
Turn 7: other — 无意义输入（唱歌）
```

**日志结构** （每轮一个目录）：
```
data/debug/test_harness/<timestamp>/case_test_room/
  turn_01/
    01_parse_prompt.txt        — Step 1 LLM prompt
    01_parse_response.json     — Step 1 LLM 返回
    02_judge.json              — Step 2 裁决结果
    03_enrich_prompt.txt       — Step 3 prompt
    03_enrich_response.json    — Step 3 LLM 返回
    04_narrator_prompt.txt     — Narrator prompt
    04_narrative.txt           — 最终叙事输出
    05_ending.json             — 结局检测
  turn_02/ ...
  _summary.json                — 7 轮总结
```

**运行**：
```bash
cd tests && python game_loop_harness.py            # 需要 API Key
cd tests && python -m pytest game_loop_harness.py   # 同样需要 API Key
```

---

## 2. Author Flow 单元测试

全部 LLM 调用 mocking，0.8s 内完成。验证 Author 介入机制的所有分支逻辑。

### 2a. IntentDetector (`tests/test_intent_detector.py`)

| 测试 | 场景 | 断言 |
|------|------|------|
| `test_detector_flavor_behavior` | 玩家唱歌 | needs_author=False |
| `test_detector_meaningful_intent` | 玩家试图与黑影对话 | needs_author=True, intent+reasoning 非空 |
| `test_detector_empty_other` | 空输入 | needs_author=False（短路返回） |

### 2b. Author Flow (`tests/test_author_flow.py`)

| 测试 | 场景 | 覆盖链路 |
|------|------|----------|
| A: `test_no_other_zero_overhead` | Parse 返回 entity 匹配 | Detector 不调用，零 overhead 验证 |
| B: `test_other_flavor_no_escalation` | other + 唱歌 | Detector→no, Author 不触发 |
| C: `test_other_meaningful_author_patch` | other + 检查座椅 | Detector→yes→Author→patch→integrate→递归 |
| D: `test_other_author_rejects` | other + 破坏场景 | Detector→yes→Author→reject→消息注入 |
| E: `test_duplicate_intent_suppressed` | 重复意图 | 同一意图在 cooldown 窗口内被抑制 |
| F: `test_author_request_fields` | 字段完整性 | AuthorRequest 各字段正确传递 |
| G: `test_integrate_supplement_connects_entry` | Supplement 集成 | 新场景注入 + from_here edge 连接 |
| H: `test_build_scene_context_for_author` | Scene context 构建 | 返回所有必需 key（wr0_enabled 等） |

**运行**：
```bash
cd tests && python -m pytest test_author_flow.py test_intent_detector.py -v
```

---

## 3. Escalation Harness (`tests/test_escalation_harness.py`)

基于《常暗之厢》测试房间 + 6号车厢场景的 5个集成 case。LLM 全 mock，但使用与生产一致的实体结构。

| Case | 场景 | 输入 | 流程 |
|------|------|------|------|
| A | 正常 entity 匹配 | "仔细检查桌子上的每样东西" | Parse→IT1→Judge→Enrich，Detector 不触发 |
| B | other + flavor | "唱了一首快乐的小曲" | Parse→other→Detector(无意义)→正常流程 |
| C | other → Author Patch | "检查桌子底下有没有暗格" | Detect→Author(patch)→integrate→递归→entity 注入 |
| D | other → Author Reject | "拿出手机打开闪光灯照向黑暗" | Detect→Author(reject, 违反 L3 forbidden)→消息注入 |
| E | other → StructuralEdit | "透过裂痕镜子与黑暗存在沟通" | Detect→Author(structural)→补充管线→镜中世界注入→graph+L3 更新 |

**日志结构**（每个 case 一个目录）：
```
data/debug/test_escalation/<timestamp>/
  case_a_normal_entity/
    _case_log.json             — case 总结（detector_called, author_called, flow）
  case_b_other_flavor/
    _case_log.json
  case_c_author_patch/
    author_prompt.txt          — Author LLM prompt 原文
    author_response.json       — Author LLM 返回
    _case_log.json             — case 总结
  case_d_author_reject/
    author_prompt.txt
    author_response.json
    _case_log.json
  case_e_author_structural/
    author_prompt.txt          — Author 判定 structural 的 prompt
    author_response.json       — 含 entry_scene, level: structural
    _case_log.json             — 含 supplement_scenes, supplement_entities
  _summary.json                — 5 case 结果汇总
```

**日志文件说明**：
- `author_prompt.txt` — 仅 Case C/D/E（Author 被触发时）生成，包含完整的 L3 上下文 + 场景信息 + WR0 状态
- `author_response.json` — Author LLM 的模拟返回（entities、level、justification）
- `_case_log.json` — 所有 case 生成，记录 Detector/Author 是否被调用、流程走向、判定结果

**运行**：
```bash
cd tests && python test_escalation_harness.py                            # 串行 4 case
cd tests && python -m pytest test_escalation_harness.py -v               # pytest 隔离运行
```

---

## 测试覆盖矩阵

| 流程分支 | Game Loop | Unit | Escalation |
|----------|-----------|------|------------|
| 正常 entity 匹配 | T1-T6 | A | A |
| Search + 侦查检定 | T1 | — | — |
| ##GRADED## 分级 | T3, T4, T5 | — | — |
| Trait enhancement | T1, T3-T5 | — | — |
| 移动 + 新场景 | T6 | — | — |
| other + flavor (不触发) | T7 | B | B |
| other + Patch (触发) | — | C | C |
| other + Reject (打回) | — | D | D |
| other + StructuralEdit (补充管线) | — | — | E |
| 重复意图抑制 | — | E | — |
| Supplement 集成 | — | G | E |
| Scene context 构建 | — | H | — |
| AuthorRequest 字段 | — | F | — |
| WR0 开关 | — | F, H | D |
