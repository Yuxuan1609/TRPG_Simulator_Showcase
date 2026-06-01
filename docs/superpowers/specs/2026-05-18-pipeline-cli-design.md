# Pipeline CLI Runner — 管线命令行入口

**日期**: 2026-05-18
**状态**: 设计已确认，待实现

---

## 目标

创建一个 `run_pipeline.py` 作为 TRPG 模组解析管线的正式 CLI 入口，替代 Jupyter notebook 的手动 cell-by-cell 执行方式。

底层调用现有的 `layered_pipeline.run_pipeline()`，新增层负责：配置集中管理、中间结果持久化、手动/自动模式切换、步进交互（重试/编辑/改配置）。

---

## 架构

```
run_pipeline.py (CLI 入口 + 交互逻辑)
    │
    ├── PipelineConfig (dataclass, JSON 可序列化)
    │     ├── 路径配置
    │     ├── 模型配置
    │     ├── 执行配置
    │     └── 注入开关
    │
    ├── InteractiveRunner (状态机)
    │     ├── 步骤编排: 调用 run_pipeline()，每步前后 hook
    │     ├── 中间结果持久化
    │     ├── 断点续跑 (start_from)
    │     └── 手动模式交互循环
    │
    └── CLI 界面
          ├── 启动向导 (选择 docx、确认配置)
          ├── 手动模式: 每步显示摘要 → [c]继续 [r]重试 [e]编辑 [m]配置 [q]退出
          └── 自动模式: 全流程输出进度，结束后显示摘要
```

---

## PipelineConfig

```python
@dataclass
class PipelineConfig:
    # ── 路径 ──
    docx_path: str = ""                    # 源模组 .docx
    module_name: str = ""                  # 模组名 → data/modules/<name>/
    output_dir: str = "data/debug"         # 中间结果根目录
    weapon_lib_path: str = "data/library/core/weapons.json"
    enemy_lib_path: str = "data/library/core/enemies.json"
    skill_checks_path: str = "data/skill_checks.json"

    # ── 模型 ──
    json_model: str = "deepseek-v4-pro"
    #   合法值: deepseek-v4-pro | deepseek-v4-flash | deepseek-v4
    text_model: str = "deepseek-v4-pro"
    #   合法值: 同上
    thinking_enabled: bool = True
    reasoning_effort: str = "high"
    #   合法值: low | medium | high
    json_temperature: float = 0.3
    #   合法值: 0.0 ~ 1.0, JSON 模式推荐 ≤0.5
    text_temperature: float = 0.7
    #   合法值: 0.0 ~ 1.0, 文本模式推荐 0.5~0.9

    # ── 执行 ──
    auto_mode: bool = False                # True=全自动, False=手动步进
    start_from: str = "step_1"
    #   合法值: step_1 | step_2a | step_2bc | step_3a | step_3b | step_35 | phase_1 | phase_2
    max_retries: int = 3                   # 每步重试次数
    parallel_workers: int = 4              # ThreadPool 最大线程数

    # ── 注入 ──
    inject_wr0: bool = True                # WR0 创作者豁免
    inject_world_at: bool = True           # AT_WORLD 世界自动触发
```

### 从文件加载配置

```python
# 优先加载 config.json, 命令行参数可覆盖
config = PipelineConfig.from_json("config.json")
# 或交互式向导
config = PipelineConfig.from_wizard()
```

---

## CLI 交互流程

### 启动

```
$ python run_pipeline.py
$ python run_pipeline.py --auto --config my_config.json
$ python run_pipeline.py --start-from step_3a  # 断点续跑
```

### 手动模式交互循环

```
[Step 1a] 结构化提取...
  模型: deepseek-v4-pro | 思考: high | 耗时: 12.3s
  ✓ 7 场景, 1 角色
  中间结果: data/debug/20260518_140000/step_1/1a_structured_extraction.json
─────────────────────────────────────────
  [c]继续  [r]重试此步  [e]编辑中间JSON  [m]改模型配置  [q]退出
─────────────────────────────────────────
> r
  重试参数 (留空保持原值):
  模型 [deepseek-v4-pro]:
  思考强度 [high]:
  温度 [0.3]:
  重试中...
```

### 编辑工作流

```
> e
  可用中间文件:
    1. step_1/1a_structured_extraction.json
    2. step_1/1b_condensed_text.txt
  编辑哪个? [1]
  用 $EDITOR 打开，修改完成后按 Enter 继续...
  已重新加载 step_1/1a_structured_extraction.json
  (后续步骤将使用修改后的数据)
```

---

## 中间结果目录

```
data/debug/<timestamp>/
├── config.json                         # 运行配置快照
├── _pipeline_log.txt                   # 每步耗时/模型/重试
├── step_1/
│   ├── 1a_structured_extraction.json
│   ├── 1b_condensed_text.txt
│   └── _summary.json
├── step_2/
│   ├── 2a_interactions.json
│   ├── 2b_events.json
│   ├── 2b_auto_triggers.json
│   ├── 2c_l1.json
│   ├── 2c_l3.json
│   └── _summary.json
├── step_25/25_npc_profiles.json
├── step_3/
│   ├── 3a_dedup_conflict.json
│   └── 3b_cross_check.json
├── step_35/35_dependency_graph.json
├── phase_1/phase1_style_preview.json
├── phase_2/phase2_standardization.json
├── _validation_report.json
└── output/                             # 最终产物
    ├── l1_player.json
    ├── l2_keeper.json
    └── l3_designer.json
```

---

## 实现策略

### 核心问题：如何在 `run_pipeline()` 单次调用中实现步进交互

`run_pipeline()` 是一个整体函数，内部串联所有步骤。要支持"每步暂停 → 确认/重试/编辑"，需要一种机制来拦截步骤间的控制流。

### StepCallback 协议

在 `run_pipeline()` 中新增可选参数 `on_step`:

```python
StepCallback = Callable[[str, dict, dict], str]
# step_name: 当前步骤名 (如 "step_1a")
# step_result: 该步骤的 LLM 返回 (dict)
# step_state: 当前累积的 PipelineResult (可读写)
# 返回: "continue" | "retry" | "abort"
```

`run_pipeline()` 每步完成后调用 `on_step`。返回 `"retry"` 时重新执行当前步骤（使用 `_with_fallback` 逻辑），返回 `"abort"` 时抛出一个特定异常。

**对 `layered_pipeline.py` 的修改**：
- `run_pipeline()` 签名新增 `on_step: StepCallback | None = None`
- 每个步骤完成后（如 `_with_fallback` 返回后）调用 `on_step`
- 返回 `"retry"` 时循环重试（用新的 callable）
- 返回 `"abort"` 时抛出 `PipelineAborted` 异常
- 参数为 `None`（默认）时行为不变，向后兼容

**修改量**：约 15 行，分散在 7 个步骤调用点。

### LLM 日志包装

LLM 日志（prompt + response 保存到磁盘）通过包装 `llm_json`/`llm_text` callable 实现，不变更 `llm.py`:

```python
def _make_llm_with_logging(base_llm, output_dir):
    """包装 LLM callable，自动保存 prompt + response."""
    def wrapped(prompt, *, system=None, json_mode=True, **kwargs):
        call_name = _next_call_name()  # 自增计数器
        save_prompt(output_dir, call_name, prompt, system)
        result = base_llm(prompt, system=system, json_mode=json_mode, **kwargs)
        save_response(output_dir, call_name, result)
        return result
    return wrapped
```

### 手动模式重试

重试某步骤时，Runner 构造新的 LLM callable（使用更新后的配置参数），再次调用 `run_pipeline()` 的对应步骤。但由于 `run_pipeline()` 是整体函数，重试需要从该步骤重新开始执行。

简化方案：手动模式下 Runner 直接调用 `layered_parser` 里的 `parse_step*` 函数，绕过 `run_pipeline()`。Runner 持有累积的 `PipelineResult`，自行编排步骤顺序。这与 notebook 的模式一致——每个 cell 直接调用 `do_json_call` + `build_*_prompt`。

**结论：Runner 分两层**

1. **自动模式**：直接调用 `run_pipeline()`（全流程，简单）
2. **手动模式**：Runner 自行编排步骤，逐步骤调用 `parse_step*` 函数 + `ThreadPoolExecutor`。用 `on_step` 回调实现暂停/重试/编辑循环。实质上是将 notebook 的 cell 逻辑迁移到 Runner 类中。

这避免了修改 `run_pipeline()` 的签名，同时保持手动模式的灵活性。

### 文件变更

| 文件 | 变更 |
|------|------|
| `run_pipeline.py` (新建) | CLI 入口 + InteractiveRunner + PipelineConfig |
| `src/llm.py` | 无变更 |
| `src/module_designer/layered_pipeline.py` | 加 `on_step` 回调参数（~15行） |
| `src/module_designer/layered_parser.py` | 无变更 |
| `docs/superpowers/specs/NEXT-SESSION.md` | 新增 runner 说明 |

### 不做的

- 不做 Web 前端（本次仅 CLI）
- 不断点续跑的 JSON 状态恢复（start_from 跳过已完成步骤，但不恢复内存状态——需从头跑管线）
- 不修改 `run_pipeline()` 的核心逻辑

---

## 验证

```bash
# 导入检查
python -c "from run_pipeline import PipelineConfig, InteractiveRunner; print('OK')"

# 配置序列化往返
python -c "from run_pipeline import PipelineConfig; c = PipelineConfig(); j = c.to_json(); c2 = PipelineConfig.from_json(j); assert c == c2"

# 实际跑一次 (自动模式, 需要 API key)
python run_pipeline.py --docx "常暗之厢（7版规则，简体修正版）.docx" --auto --module 常暗之厢
```
