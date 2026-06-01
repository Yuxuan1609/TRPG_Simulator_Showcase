"""
run_pipeline.py — TRPG 模组解析管线 CLI 入口

用法:
  python run_pipeline.py                           # 交互式配置向导 → 手动步进
  python run_pipeline.py --auto --docx <路径>       # 自动模式（全流程）
  python run_pipeline.py --config config.json       # 从配置文件加载


  python run_pipeline.py --start-from step_3a       # 从指定步骤断点续跑（需已有中间文件）

架构:
  PipelineConfig  → 集中配置（dataclass, JSON 序列化, 交互向导）
  InteractiveRunner → 手动/自动模式编排, 中间结果持久化, 步进交互
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

# ── 项目路径 ──
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from llm import call_deepseek
from utils import parser as parse_docx, estimate_and_truncate_context


def _load_document(path: str) -> str:
    """加载文档内容，根据扩展名选择解析器。
    支持: .docx (Word), .txt (纯文本), .pdf (PDF)
    """
    ext = Path(path).suffix.lower()
    if ext == ".docx":
        return parse_docx(path)
    elif ext == ".txt":
        return Path(path).read_text(encoding="utf-8")
    elif ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(path)
            return "\n".join(
                page.extract_text() or "" for page in reader.pages
            )
        except ImportError:
            print("错误：PDF 解析需要 pypdf 库。运行: pip install pypdf")
            sys.exit(1)
    else:
        supported = ", ".join(SUPPORTED_FORMATS)
        print(f"错误：不支持的文档格式 '{ext}'。支持: {supported}")
        sys.exit(1)


SUPPORTED_FORMATS = (".docx", ".txt", ".pdf")


def _pick_file_gui() -> str:
    """使用 tkinter 原生文件对话框选择文档。失败返回空字符串。"""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        filetypes = [
            ("支持的文档", "*.docx;*.pdf;*.txt"),
            ("Word 文档", "*.docx"),
            ("PDF 文件", "*.pdf"),
            ("纯文本", "*.txt"),
        ]
        path = filedialog.askopenfilename(
            title="选择模组文档",
            filetypes=filetypes,
        )
        root.destroy()
        return path or ""
    except Exception:
        return ""


def _pick_file_scan() -> str:
    """扫描当前目录及子目录，列出支持的文档供用户选择。"""
    import glob as _glob
    cwd = Path.cwd()
    candidates = []
    for ext in SUPPORTED_FORMATS:
        candidates.extend(cwd.glob(f"*{ext}"))
        candidates.extend(cwd.glob(f"**/*{ext}"))

    # 去重排序
    candidates = sorted(set(candidates), key=lambda p: (p == cwd, p))

    if not candidates:
        print(f"  当前目录未找到 {', '.join(SUPPORTED_FORMATS)} 文件")
        return ""

    print(f"\n  当前目录找到 {len(candidates)} 个文档:")
    for i, p in enumerate(candidates, 1):
        rel = p.relative_to(cwd) if p.is_relative_to(cwd) else p
        size_kb = p.stat().st_size / 1024
        print(f"    {i:2}. {rel} ({size_kb:.0f} KB)")

    print(f"    0.  手动输入路径")
    while True:
        choice = input("  选择 [1]: ").strip()
        if not choice or choice == "1":
            idx = 0
        else:
            try:
                idx = int(choice) - 1
            except ValueError:
                continue
        if idx == -1:
            return input("  输入路径: ").strip().strip('"')
        if 0 <= idx < len(candidates):
            return str(candidates[idx])
from module_designer import (
    validate_all, save_pipeline_result,
    build_step1a_prompt, build_step1b_prompt,
    build_step2a_prompt, build_step2b_combined_prompt,
    build_step2c_l1_prompt, build_step2c_l3_prompt,
    build_step3a_prompt, build_step35_prompt,
    build_step4_prompt, build_step2_boss_prompt,
    parse_step25_combined,
    _with_fallback,
)
from module_designer.layered_parser import (
    _parse_condensed_chapters, _merge_phase2_fields, _slim_entity,
    STEP1A_SYSTEM, STEP1B_SYSTEM,
    STEP2A_SYSTEM, STEP2B_COMBINED_SYSTEM,
    STEP2C_L1_SYSTEM, STEP2C_L3_SYSTEM,
    STEP3A_SYSTEM, STEP35_SYSTEM,
    parse_step3b, STEP4_SYSTEM, STEP2_BOSS_SYSTEM,
)
from module_designer.layered_pipeline import (run_pipeline, cross_validate_layers, _assemble_l2,
    _bind_npc_entities, _extract_entity_bindings, _inject_step1a_meta,
    _inject_npc_special_entities)
from module_designer.dependency_graph import DependencyGraph
from library import WeaponLibrary, EnemyLibrary
from library.bosses import BossLibrary


# ═══════════════════════════════════════════════════════════════
#  PipelineConfig
# ═══════════════════════════════════════════════════════════════

VALID_MODELS = ("deepseek-v4-pro", "deepseek-v4-flash")
VALID_REASONING_EFFORT = ("low", "medium", "high", "max")
VALID_START_FROM = (
    "step_1", "step_2a", "step_2bc", "step_3a", "step_3b",
    "step_35", "phase_1", "phase_2",
)

# 步骤 → 描述
STEP_NAMES = {
    "step_1":    "Step 1a+1b: 结构化提取 + 精修模组（并行）",
    "step_2a":   "Step 2a: 互动项提取",
    "step_2bc":  "Step 2b+2c: 事件 + 自动触发 + L1 玩家层 + L3 设计层（并行）",
    "step_3a":   "Step 3a+2.5: 去重冲突 + NPC档案+实体归属（并行）",
    "step_3b":   "Step 3b: L1 ↔ L2 交叉核对",
    "step_35":   "Step 3.5+Phase 1: 依赖图构建 + 约束提取",
    "phase_2":   "Phase 2: 精简标准化 → 组装 → 验证 → 保存",
}


@dataclass
class PipelineConfig:
    """管线运行配置，所有字段可通过 JSON 序列化。"""

    # ── 路径 ──
    docx_path: str = ""
    #   源模组文档路径（相对于项目根目录或绝对路径）
    #   支持格式: .docx (Word), .pdf (PDF), .txt (纯文本)
    module_name: str = ""
    #   模组名称，用于输出目录 data/modules/<name>/
    output_dir: str = "data/debug"
    #   中间结果输出根目录（相对于项目根目录）
    weapon_lib_path: str = "data/library/core/weapons.json"
    enemy_lib_path: str = "data/library/core/enemies.json"
    boss_lib_path: str = "data/library/core/bosses.json"
    skill_checks_path: str = "data/skill_checks.json"

    # ── 模型 ──
    json_model: str = "deepseek-v4-pro"
    #   合法值: deepseek-v4-pro | deepseek-v4-flash
    #   JSON 模式（结构化提取/判定）使用此模型
    text_model: str = "deepseek-v4-pro"
    #   合法值: 同 json_model
    #   文本模式（精修叙事）使用此模型
    thinking_enabled: bool = True
    #   是否启用思考模式（DeepSeek reasoning）
    reasoning_effort: str = "high"
    #   推理深度: low（快但浅） | medium | high | max（最深度推理）
    json_temperature: float = 0.3
    #   JSON 模式温度（0.0 ~ 1.0），推荐 0.1~0.4 保证结构化输出稳定性
    text_temperature: float = 0.7
    #   文本模式温度（0.0 ~ 1.0），推荐 0.5~0.9 保证叙事多样性

    # ── 执行 ──
    auto_mode: bool = False
    #   True = 全流程自动执行（无交互）
    #   False = 每步完成后暂停 → [c]继续 [r]重试 [e]编辑 [m]改配置 [q]退出
    start_from: str = "step_1"
    #   断点续跑起点: step_1 | step_2a | step_2bc | step_3a | step_3b | step_35 | phase_1 | phase_2
    max_retries: int = 3
    #   每步 LLM 调用（含 JSON 解析失败）的最大重试次数
    parallel_workers: int = 4
    #   并行步骤的最大线程数

    # ── 注入开关 ──
    inject_wr0: bool = True
    #   是否在 L3 注入 WR0 创作者豁免规则
    inject_world_at: bool = True
    #   是否注入 AT_WORLD 世界自动触发

    def to_dict(self) -> dict:
        """序列化为 JSON 兼容 dict。"""
        return asdict(self)

    def to_json(self, path: str) -> None:
        """保存配置到 JSON 文件。"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, d: dict) -> "PipelineConfig":
        """从 dict 加载配置，忽略未知字段。"""
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in valid_keys}
        return cls(**filtered)

    @classmethod
    def from_json(cls, path: str) -> "PipelineConfig":
        """从 JSON 文件加载配置。"""
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    @classmethod
    def from_wizard(cls) -> "PipelineConfig":
        """交互式配置向导。返回配置实例。"""
        print("=" * 50)
        print("  TRPG 模组解析管线 — 配置向导")
        print("=" * 50)
        print()

        # ── 路径 ──
        print("源文档选择:")
        print("  [Enter] 浏览当前目录下的文档")
        print("  或直接输入路径 (.docx/.pdf/.txt)")
        docx_path = input("> ").strip().strip('"')

        if not docx_path:
            # 尝试 tkinter 文件对话框
            docx_path = _pick_file_gui()
            if not docx_path:
                # 回退：扫描当前目录
                docx_path = _pick_file_scan()
        if not docx_path:
            print("错误：必须提供源文档路径")
            sys.exit(1)

        module_name = input(f"模组名称 [从文件名推断]: ").strip()

        # ── 模型 ──
        print()
        print(f"JSON 模型 [{VALID_MODELS[0]}]: ", end="")
        print(f"   ({' | '.join(VALID_MODELS)})")
        json_model = input("> ").strip() or VALID_MODELS[0]

        print(f"文本模型 [{VALID_MODELS[0]}]: ", end="")
        print(f"   ({' | '.join(VALID_MODELS)})")
        text_model = input("> ").strip() or VALID_MODELS[0]

        thinking = input("启用思考模式 [Y/n]: ").strip().lower()
        thinking_enabled = thinking != "n"

        if thinking_enabled:
            print(f"推理强度 [high]: ", end="")
            print(f"   ({' | '.join(VALID_REASONING_EFFORT)})")
            effort = input("> ").strip() or "high"
        else:
            effort = "high"

        print(f"JSON 温度 [{0.3}]: ", end="")
        j_temp = input("> ").strip()
        json_temperature = float(j_temp) if j_temp else 0.3

        print(f"文本温度 [{0.7}]: ", end="")
        t_temp = input("> ").strip()
        text_temperature = float(t_temp) if t_temp else 0.7

        # ── 执行 ──
        print()
        mode = input("执行模式: [M]手动步进 / [A]自动全流程? ").strip().lower()
        auto_mode = mode == "a"

        if not auto_mode:
            print(f"起始步骤 [{VALID_START_FROM[0]}]:")
            for s in VALID_START_FROM:
                print(f"  {s}: {STEP_NAMES.get(s, s)}")
            start_from = input("> ").strip() or VALID_START_FROM[0]
        else:
            start_from = VALID_START_FROM[0]

        print(f"最大重试次数 [3]: ", end="")
        mr = input("> ").strip()
        max_retries = int(mr) if mr else 3

        print(f"并行线程数 [4]: ", end="")
        pw = input("> ").strip()
        parallel_workers = int(pw) if pw else 4

        # ── 注入 ──
        print()
        wr0 = input("注入 WR0 创作者豁免 [Y/n]: ").strip().lower()
        inject_wr0 = wr0 != "n"

        wat = input("注入 AT_WORLD 世界触发 [Y/n]: ").strip().lower()
        inject_world_at = wat != "n"

        return cls(
            docx_path=docx_path,
            module_name=module_name,
            json_model=json_model,
            text_model=text_model,
            thinking_enabled=thinking_enabled,
            reasoning_effort=effort,
            json_temperature=json_temperature,
            text_temperature=text_temperature,
            auto_mode=auto_mode,
            start_from=start_from,
            max_retries=max_retries,
            parallel_workers=parallel_workers,
            inject_wr0=inject_wr0,
            inject_world_at=inject_world_at,
        )


# ═══════════════════════════════════════════════════════════════
#  LLM 包装器 — 日志记录
# ═══════════════════════════════════════════════════════════════

class LLMLogger:
    """包装 LLM callable，自动保存每次调用的 prompt + response 到输出目录。

    用法:
        logger = LLMLogger(output_dir)
        llm_json = logger.wrap_json(config)   # 返回 callable
        llm_text = logger.wrap_text(config)   # 返回 callable
    """

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self._counter = 0
        self._calls: list[dict] = []

    def _next_name(self) -> str:
        self._counter += 1
        return f"{self._counter:02d}"

    def wrap_json(self, config: PipelineConfig) -> Callable:
        """创建 JSON 模式 LLM callable，带日志记录。

        返回的 callable 签名: llm_json(prompt, *, system=None, call_name=None) -> dict
        call_name: 若提供则用作日志目录名（如 "step1a"），否则自动编号。
        """
        logger = self

        def llm_json(prompt: str, *, system: str | None = None, call_name: str | None = None) -> dict:
            name = call_name if call_name else logger._next_name()
            call_dir = logger.output_dir / "_llm_calls" / name
            call_dir.mkdir(parents=True, exist_ok=True)

            # 保存 prompt
            with open(call_dir / "prompt.txt", "w", encoding="utf-8") as f:
                if system:
                    f.write(f"=== SYSTEM ===\n{system}\n\n=== USER ===\n{prompt}")
                else:
                    f.write(prompt)

            t0 = time.time()
            result = call_deepseek(
                prompt, json_mode=True, system=system,
                model=config.json_model,
                thinking=config.thinking_enabled,
                reasoning_effort=config.reasoning_effort,
                temperature=config.json_temperature,
                max_retries=config.max_retries,
            )
            elapsed = time.time() - t0

            # 保存 response
            with open(call_dir / "response.json", "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            logger._calls.append({
                "name": name, "model": config.json_model,
                "thinking": config.thinking_enabled,
                "effort": config.reasoning_effort,
                "elapsed_s": round(elapsed, 1),
                "result_keys": list(result.keys()) if isinstance(result, dict) else [],
            })
            return result

        return llm_json

    def wrap_text(self, config: PipelineConfig) -> Callable:
        """创建文本模式 LLM callable，带日志记录。

        返回的 callable 签名: llm_text(prompt, *, system=None, call_name=None) -> str
        """
        logger = self

        def llm_text(prompt: str, *, system: str | None = None, call_name: str | None = None) -> str:
            name = call_name if call_name else logger._next_name()
            call_dir = logger.output_dir / "_llm_calls" / name
            call_dir.mkdir(parents=True, exist_ok=True)

            # 保存 prompt
            with open(call_dir / "prompt.txt", "w", encoding="utf-8") as f:
                if system:
                    f.write(f"=== SYSTEM ===\n{system}\n\n=== USER ===\n{prompt}")
                else:
                    f.write(prompt)

            t0 = time.time()
            result = call_deepseek(
                prompt, json_mode=False, system=system,
                model=config.text_model,
                thinking=config.thinking_enabled,
                reasoning_effort=config.reasoning_effort,
                temperature=config.text_temperature,
            )
            elapsed = time.time() - t0

            # 保存 response
            with open(call_dir / "response.txt", "w", encoding="utf-8") as f:
                f.write(str(result))

            logger._calls.append({
                "name": name, "model": config.text_model,
                "thinking": config.thinking_enabled,
                "effort": config.reasoning_effort,
                "elapsed_s": round(elapsed, 1),
            })
            return result

        return llm_text

    @property
    def call_log(self) -> list[dict]:
        return self._calls


# ═══════════════════════════════════════════════════════════════
#  InteractiveRunner
# ═══════════════════════════════════════════════════════════════

class PipelineAborted(Exception):
    """用户手动中止管线。"""
    pass


class InteractiveRunner:
    """管线运行器：自动模式（委托 run_pipeline）或手动步进模式。

    手动模式每步完成后显示摘要，等待用户确认：
      [c]继续  [r]重试  [e]编辑中间JSON  [m]改配置  [q]退出
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = PROJECT_ROOT / config.output_dir / self.timestamp
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # LLM 日志
        self.llm_logger = LLMLogger(self.output_dir)
        self.llm_json = self.llm_logger.wrap_json(config)
        self.llm_text = self.llm_logger.wrap_text(config)

        # 库
        self.wl: WeaponLibrary | None = None
        self.el: EnemyLibrary | None = None
        self.bl: BossLibrary | None = None

        # 输入
        self.content: str = ""  # 源文档全文（由 run_* 函数设置）

        # 中间状态（逐步累积）
        self.step1a: dict = {}
        self.step1b: dict = {}
        self.chapters: dict[str, str] = {}
        self.scenes: list = []
        self.characters: list = []
        self.interactions: list = []
        self.scene_movements: dict = {}
        self.events: list = []
        self.auto_triggers: list = []
        self.l1_data: dict = {}
        self.l3_data: dict = {}
        self.npc_profiles: dict = {}
        self.l2_assembled: dict = {}
        self.dep_graph: DependencyGraph | None = None
        self.phase1_clean: dict = {}

        # 步骤完成追踪
        self._completed_steps: set[str] = set()
        self._current_step: str = ""

    # ── 工具 ──

    def _step_dir(self, step_name: str) -> Path:
        d = self.output_dir / step_name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _save_summary(self, step_name: str, data: dict):
        with open(self._step_dir(step_name) / "_summary.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _prompt_user(self, step_name: str, summary: str) -> str:
        """显示步骤摘要，等待用户输入。返回 'c'/'r'/'e'/'m'/'q'。"""
        print()
        print(f"\033[90m{'─' * 55}\033[0m")
        print(f"  {summary}")
        print(f"  中间结果: {self._step_dir(step_name)}")
        print(f"\033[90m{'─' * 55}\033[0m")
        print("  \033[1m[c]\033[0m继续  \033[1m[r]\033[0m重试此步  \033[1m[e]\033[0m编辑中间JSON  \033[1m[m]\033[0m改配置  \033[1m[q]\033[0m退出")
        while True:
            choice = input("> ").strip().lower()
            if choice in ("c", "r", "e", "m", "q", ""):
                return choice or "c"
            print("  无效输入，请选择 c/r/e/m/q")

    def _handle_retry(self, step_name: str) -> bool:
        """处理重试：允许修改配置后重新执行当前步骤。返回 True 表示需要重做。"""
        print(f"\n  重试 {step_name}。覆盖参数（留空保持原值）:")
        model = input(f"  模型 [{self.config.json_model}]: ").strip()
        if model:
            self.config.json_model = model
            self.config.text_model = model
            # 重建 LLM callable
            self.llm_json = self.llm_logger.wrap_json(self.config)
            self.llm_text = self.llm_logger.wrap_text(self.config)
        effort = input(f"  推理强度 [{self.config.reasoning_effort}]: ").strip()
        if effort:
            self.config.reasoning_effort = effort
            self.llm_json = self.llm_logger.wrap_json(self.config)
            self.llm_text = self.llm_logger.wrap_text(self.config)
        temp = input(f"  JSON 温度 [{self.config.json_temperature}]: ").strip()
        if temp:
            self.config.json_temperature = float(temp)
            self.llm_json = self.llm_logger.wrap_json(self.config)
        return True

    def _handle_edit(self, step_name: str):
        """列出当前步骤的中间文件，让用户选择编辑。"""
        step_dir = self._step_dir(step_name)
        files = sorted(step_dir.glob("*.json")) + sorted(step_dir.glob("*.txt"))
        files = [f for f in files if not f.name.startswith("_")]
        if not files:
            print("  此步骤无中间 JSON 文件")
            return
        print("  可用中间文件:")
        for i, f in enumerate(files, 1):
            print(f"    {i}. {f.relative_to(self.output_dir)}")
        choice = input(f"  编辑哪个? [1-{len(files)}/Enter 跳过]: ").strip()
        if not choice:
            return
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(files):
                path = str(files[idx])
                editor = os.environ.get("EDITOR", "notepad")
                print(f"  启动编辑器: {editor} {path}")
                print(f"  编辑完成后按 Enter 继续...")
                os.system(f'{editor} "{path}"')
                input("  按 Enter 确认已保存...")
                print(f"  已重新加载: {path}")
        except (ValueError, IndexError):
            print("  无效选择")

    def _handle_config_change(self):
        """运行时修改配置。"""
        print(f"  当前配置:")
        print(f"    模型: json={self.config.json_model}, text={self.config.text_model}")
        print(f"    思考: {self.config.thinking_enabled}, 强度={self.config.reasoning_effort}")
        print(f"    温度: json={self.config.json_temperature}, text={self.config.text_temperature}")
        print(f"    重试: {self.config.max_retries}, 并行: {self.config.parallel_workers}")
        print()
        print("  修改参数（留空保持原值）:")

        model = input(f"  JSON 模型 [{self.config.json_model}]: ").strip()
        if model and model in VALID_MODELS:
            self.config.json_model = model
        elif model:
            print(f"    警告: 未知模型 '{model}'，保持原值")

        tmodel = input(f"  文本模型 [{self.config.text_model}]: ").strip()
        if tmodel and tmodel in VALID_MODELS:
            self.config.text_model = tmodel
        elif tmodel:
            print(f"    警告: 未知模型 '{tmodel}'，保持原值")

        think = input(f"  思考模式 [{'Y' if self.config.thinking_enabled else 'N'}]: ").strip().lower()
        if think == "n":
            self.config.thinking_enabled = False
        elif think == "y":
            self.config.thinking_enabled = True

        effort = input(f"  推理强度 [{self.config.reasoning_effort}]: ").strip()
        if effort in VALID_REASONING_EFFORT:
            self.config.reasoning_effort = effort

        jt = input(f"  JSON 温度 [{self.config.json_temperature}]: ").strip()
        if jt:
            try:
                self.config.json_temperature = float(jt)
            except ValueError:
                print(f"    警告: 无效温度值")

        tt = input(f"  文本温度 [{self.config.text_temperature}]: ").strip()
        if tt:
            try:
                self.config.text_temperature = float(tt)
            except ValueError:
                print(f"    警告: 无效温度值")

        mr = input(f"  最大重试 [{self.config.max_retries}]: ").strip()
        if mr:
            try:
                self.config.max_retries = int(mr)
            except ValueError:
                print(f"    警告: 无效值")

        # 重建 LLM callable
        self.llm_json = self.llm_logger.wrap_json(self.config)
        self.llm_text = self.llm_logger.wrap_text(self.config)
        print(f"  配置已更新")

    def _interact(self, step_name: str, summary: str) -> None:
        """手动模式交互循环。可能触发重试循环或抛出 PipelineAborted。"""
        while True:
            choice = self._prompt_user(step_name, summary)
            if choice == "c":
                return
            elif choice == "r":
                self._handle_retry(step_name)
                raise _RetryStep()
            elif choice == "e":
                self._handle_edit(step_name)
            elif choice == "m":
                self._handle_config_change()
            elif choice == "q":
                print("\n  管线已中止。中间结果已保存。")
                raise PipelineAborted()


class _RetryStep(Exception):
    """内部控制：重试当前步骤。"""
    pass


# ═══════════════════════════════════════════════════════════════
#  管线步骤
# ═══════════════════════════════════════════════════════════════

def _do_step1(runner: InteractiveRunner, verbose: bool = True):
    """Step 1a + 1b: 结构化提取 + 精修模组（并行）。"""
    config = runner.config

    if verbose:
        print("\n\033[1m[Step 1] 结构化提取 + 精修模组（并行）\033[0m")

    weapon_names_1a = [w.name for w in runner.wl.list_all()] if runner.wl else []
    enemy_names_1a = [e.name for e in runner.el.list_all()] if runner.el else []
    boss_names_1a = runner.bl.list_names() if runner.bl else []

    def _do_1a():
        prompt = build_step1a_prompt(runner.content, weapon_names_1a, enemy_names_1a, boss_names_1a)
        return runner.llm_json(prompt, system=STEP1A_SYSTEM, call_name="step1a_structured_extract")

    def _do_1b():
        prompt = build_step1b_prompt(runner.content)
        return runner.llm_text(prompt, system=STEP1B_SYSTEM, call_name="step1b_condense")

    # 并行执行（不使用 _with_fallback，手动处理）
    with ThreadPoolExecutor(max_workers=2) as ex:
        f1a = ex.submit(_do_1a)
        f1b = ex.submit(_do_1b)
        runner.step1a = f1a.result()
        step1b_raw = f1b.result()

    runner.step1b = {"condensed_text": step1b_raw} if isinstance(step1b_raw, str) else step1b_raw
    runner.scenes = runner.step1a.get("scenes", [])
    runner.characters = runner.step1a.get("characters", [])
    condensed_text = runner.step1b.get("condensed_text", "")
    runner.chapters = _parse_condensed_chapters(condensed_text) if condensed_text else {}

    # 保存中间结果
    step_dir = runner._step_dir("step_1")
    with open(step_dir / "1a_structured_extraction.json", "w", encoding="utf-8") as f:
        json.dump(runner.step1a, f, ensure_ascii=False, indent=2)
    with open(step_dir / "1b_condensed_text.txt", "w", encoding="utf-8") as f:
        f.write(condensed_text)
    runner._save_summary("step_1", {
        "scenes": runner.scenes,
        "characters": runner.characters,
        "condensed_text_length": len(condensed_text),
        "chapters": list(runner.chapters.keys()),
    })

    if verbose:
        print(f"  ✓ Step 1a: {len(runner.scenes)} 场景, {len(runner.characters)} 角色")
        print(f"  ✓ Step 1b: {len(condensed_text)} 字符 condensed_text, {len(runner.chapters)} chapters")

    return f"Step 1 完成: {len(runner.scenes)} 场景, {len(runner.characters)} 角色, {len(condensed_text)} 字符"


def _do_step2a(runner: InteractiveRunner, verbose: bool = True):
    """Step 2a: Interactions 提取。"""
    if verbose:
        print("\n\033[1m[Step 2a] Interactions 提取\033[0m")

    # Load skill names for type whitelist
    skill_names = []
    skill_path = PROJECT_ROOT / runner.config.skill_checks_path
    if skill_path.exists():
        with open(skill_path, "r", encoding="utf-8") as f:
            skill_checks = json.load(f)
            skill_names = sorted(set(s["name"] for s in skill_checks))

    def _do():
        prompt = build_step2a_prompt(runner.chapters, runner.scenes, runner.characters, skill_names=skill_names)
        return runner.llm_json(prompt, system=STEP2A_SYSTEM, call_name="step2a_interactions")

    step2a = _do()  # Step 2a 较简单，直接调用
    runner.interactions = step2a.get("interactions", [])
    runner.scene_movements = step2a.get("scene_movements", {})

    # 保存
    step_dir = runner._step_dir("step_2a")
    with open(step_dir / "2a_interactions.json", "w", encoding="utf-8") as f:
        json.dump(step2a, f, ensure_ascii=False, indent=2)
    runner._save_summary("step_2a", {
        "interactions_count": len(runner.interactions),
        "scene_movements_count": len(runner.scene_movements),
    })

    if verbose:
        print(f"  ✓ {len(runner.interactions)} interactions, {len(runner.scene_movements)} 场景通行路径")

    return f"Step 2a 完成: {len(runner.interactions)} interactions"


def _do_step2bc(runner: InteractiveRunner, verbose: bool = True):
    """Step 2b + 2c: Events+AT (合并) + L1 + L3（并行）。"""
    config = runner.config
    if verbose:
        print("\n\033[1m[Step 2b+2c] Events+AT (合并) + L1 + L3（并行）\033[0m")

    def _do_step2b():
        prompt = build_step2b_combined_prompt(runner.chapters, runner.scenes, runner.interactions,
                                               runner.characters,
                                               enemies=runner.step1a.get("enemies", []),
                                               weapons=runner.step1a.get("weapons", []))
        return runner.llm_json(prompt, system=STEP2B_COMBINED_SYSTEM, call_name="step2b_combined")

    def _do_l1():
        prompt = build_step2c_l1_prompt(runner.chapters, runner.scenes, runner.characters)
        return runner.llm_json(prompt, system=STEP2C_L1_SYSTEM, call_name="step2c_l1")

    def _do_l3():
        prompt = build_step2c_l3_prompt(
            runner.chapters, runner.scenes, runner.characters,
            runner.step1a.get("module_meta", {}),
        )
        return runner.llm_json(prompt, system=STEP2C_L3_SYSTEM, call_name="step2c_l3")

    with ThreadPoolExecutor(max_workers=min(3, config.parallel_workers)) as ex:
        f_2b = ex.submit(_do_step2b)
        f_l1 = ex.submit(_do_l1)
        f_l3 = ex.submit(_do_l3)
        step2b_data = f_2b.result()
        runner.l1_data = f_l1.result()
        runner.l3_data = f_l3.result()

    runner.events = step2b_data.get("events", [])
    runner.auto_triggers = step2b_data.get("auto_triggers", [])

    # 保存
    step_dir = runner._step_dir("step_2bc")
    with open(step_dir / "2b_combined.json", "w", encoding="utf-8") as f:
        json.dump(step2b_data, f, ensure_ascii=False, indent=2)
    with open(step_dir / "2c_l1.json", "w", encoding="utf-8") as f:
        json.dump(runner.l1_data, f, ensure_ascii=False, indent=2)
    with open(step_dir / "2c_l3.json", "w", encoding="utf-8") as f:
        json.dump(runner.l3_data, f, ensure_ascii=False, indent=2)

    if verbose:
        print(f"  ✓ Events: {len(runner.events)}, AT: {len(runner.auto_triggers)}")
        print(f"  ✓ L1: {len(runner.l1_data)} 场景, L3: {len(runner.l3_data.get('world_rules',[]))} 世界规则")

    return f"Step 2 完成: {len(runner.events)} events, {len(runner.auto_triggers)} AT"


def _do_step3a_25(runner: InteractiveRunner, verbose: bool = True):
    """Step 3a + 2.5: 去重冲突 + NPC档案+实体归属（并行）→ 绑定 → 组装 L2。"""
    if verbose:
        print("\n\033[1m[Step 3a+2.5] 去重冲突 + NPC 档案+实体归属（并行）\033[0m")

    ending_conditions = runner.l3_data.get("ending_conditions", [])
    l3_characters = runner.l3_data.get("characters", [])
    step1a_characters = runner.step1a.get("characters", [])

    def _do_3a():
        prompt = build_step3a_prompt(
            runner.chapters, runner.interactions, runner.events,
            runner.auto_triggers, ending_conditions,
        )
        return runner.llm_json(prompt, system=STEP3A_SYSTEM, call_name="step3a_dedup_conflict")

    n_workers = 1 + (1 if l3_characters else 0)
    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        f3a = ex.submit(_do_3a)
        if l3_characters:
            f25 = ex.submit(
                lambda: parse_step25_combined(
                    l3_characters, runner.l1_data,
                    runner.interactions, runner.auto_triggers,
                    lambda p, **kw: runner.llm_json(p, call_name="step25_combined", **kw),
                    step1a_characters=step1a_characters,
                )
            )
        step3a = f3a.result()
        step25 = f25.result() if l3_characters else {"npc_profiles": {}}

    runner.interactions = step3a.get("interactions", runner.interactions)
    runner.events = step3a.get("events", runner.events)
    runner.auto_triggers = step3a.get("auto_triggers", runner.auto_triggers)
    runner.npc_profiles = step25.get("npc_profiles", {})

    entity_bindings = _extract_entity_bindings(runner.npc_profiles)

    _inject_step1a_meta(runner.npc_profiles, step1a_characters, verbose)

    runner.interactions, runner.auto_triggers, runner.npc_profiles = _bind_npc_entities(
        runner.interactions, runner.auto_triggers, runner.npc_profiles,
        entity_bindings=entity_bindings if entity_bindings else None,
    )

    _inject_npc_special_entities(runner.interactions, runner.npc_profiles, verbose)

    # 保存
    step_dir_3 = runner._step_dir("step_3a")
    with open(step_dir_3 / "3a_dedup_conflict.json", "w", encoding="utf-8") as f:
        json.dump(step3a, f, ensure_ascii=False, indent=2)

    step_dir_25 = runner._step_dir("step_25")
    with open(step_dir_25 / "25_npc_profiles.json", "w", encoding="utf-8") as f:
        json.dump(step25, f, ensure_ascii=False, indent=2)

    # 组装 L2
    boss_hints = runner.step1a.get("boss_encounters", [])
    boss_encounters_data = []
    if boss_hints:
        boss_lib_names = runner.bl.list_names() if runner.bl else []
        from module_designer.layered_parser import parse_step2_boss as _parse_step2_boss
        step2_boss = _parse_step2_boss(
            boss_hints, boss_lib_names,
            runner.interactions, runner.auto_triggers,
            runner.scenes, runner.chapters,
            lambda p, **kw: runner.llm_json(p, call_name="step2_boss", **kw),
        )
        boss_encounters_data = step2_boss.get("boss_encounters", [])

    runner.l2_assembled = _assemble_l2(
        runner.interactions, runner.events, runner.auto_triggers,
        runner.scene_movements, runner.l1_data,
        npc_profiles=runner.npc_profiles,
        boss_encounters=boss_encounters_data,
    )

    if verbose:
        bound_count = sum(
            len(p.get("bound_interactions", [])) + len(p.get("bound_auto_triggers", []))
            for p in runner.npc_profiles.values()
        )
        bind_source = "LLM" if entity_bindings else "deterministic"
        print(f"  ✓ Step 3a: {len(runner.interactions)} interactions, {len(runner.events)} events, {len(runner.auto_triggers)} AT")
        print(f"  ✓ Step 2.5: {len(runner.npc_profiles)} NPC profiles, {len(entity_bindings)} bound entities ({bind_source})")
        print(f"  ✓ NPC Bind: {bound_count} entities bound to NPCs")
        print(f"  ✓ L2 组装: {len(runner.l2_assembled.get('scenes',{}))} 场景")

    return f"Step 3a+2.5 完成: {len(runner.npc_profiles)} NPC profiles, L2 已组装"


def _do_step3b(runner: InteractiveRunner, verbose: bool = True):
    """Step 3b: L1 ↔ L2 交叉核对（确定性优先 + LLM gap-fill）。"""
    if verbose:
        print("\n\033[1m[Step 3b] L1 ↔ L2 交叉核对\033[0m")

    step3b = parse_step3b(
        runner.chapters, runner.l1_data, runner.l2_assembled,
        runner.l3_data, runner.scenes,
        lambda prompt, **kw: runner.llm_json(prompt, call_name="step3b_link_fill", **kw),
    )
    runner.l1_data = step3b.get("l1_data", runner.l1_data)
    runner.l3_data = step3b.get("l3_data", runner.l3_data)

    # WR0 注入
    if runner.config.inject_wr0 and not runner.l3_data.get("_fallback"):
        world_rules = runner.l3_data.setdefault("world_rules", [])
        if "WR0" not in {wr.get("id", "") for wr in world_rules if isinstance(wr, dict)}:
            world_rules.insert(0, {
                "id": "WR0", "name": "创作者豁免",
                "rule": "所有世界规则只约束KP和玩家，模组创作者不受世界规则约束",
                "scope": ["meta"], "is_absolute": True,
            })

    # 保存
    step_dir = runner._step_dir("step_3b")
    with open(step_dir / "3b_cross_check.json", "w", encoding="utf-8") as f:
        json.dump(step3b, f, ensure_ascii=False, indent=2)

    if verbose:
        print(f"  ✓ L1: {len(runner.l1_data)} 场景, L3 scene_intents: {list(runner.l3_data.get('scene_intents', {}).keys())}")

    return f"Step 3b 完成: 交叉核对完成"


def _do_step35_phase1(runner: InteractiveRunner, verbose: bool = True):
    """Step 3.5 + Phase 1: 依赖图 + 风格预判（并行）。"""
    config = runner.config
    if verbose:
        print("\n\033[1m[Step 3.5] 依赖图\033[0m")

    # 从组装的 L2 提取平面实体列表
    step35_interactions = []
    step35_at = []
    for sdata in runner.l2_assembled.get("scenes", {}).values():
        step35_interactions.extend(sdata.get("interactions", []))
        step35_at.extend(sdata.get("auto_triggers", []))
    step35_events = runner.l2_assembled.get("events", [])

    def _do_35():
        """依赖图（含重试逻辑）"""
        max_tries = 3
        for attempt in range(1, max_tries + 1):
            prompt = build_step35_prompt(
                runner.chapters, step35_interactions, step35_events, step35_at,
            )
            step35 = runner.llm_json(prompt, system=STEP35_SYSTEM, call_name="step35_dep_graph")
            deps = step35.get("dependencies", [])
            if not deps:
                if attempt < max_tries:
                    print(f"    [Step 3.5] 第 {attempt} 次解析为空，重试...")
                    continue
                return None
            graph = DependencyGraph()
            graph.build(deps)
            cycles = graph.detect_cycles()
            if not cycles:
                print(f"    [Step 3.5] 依赖图: {len(graph.nodes)} 节点, {len(graph.edges)} 边, 无循环")
                return graph
            if attempt < max_tries:
                print(f"    [Step 3.5] 第 {attempt} 次检测到 {len(cycles)} 个循环，重试...")
            else:
                graph.cut_random_edge_in_cycles()
                print(f"    [Step 3.5] 重调用尽，随机切断循环边")
                return graph
        return None

    runner.dep_graph = _do_35()

    # Enemy/weapon constraints now come from Step 1a (merged Phase 1)
    runner.phase1_clean = {
        "enemies": runner.step1a.get("enemies", []),
        "weapons": runner.step1a.get("weapons", []),
    }

    # 保存
    if runner.dep_graph:
        step_dir_35 = runner._step_dir("step_35")
        with open(step_dir_35 / "35_dependency_graph.json", "w", encoding="utf-8") as f:
            json.dump(runner.dep_graph.to_dict(), f, ensure_ascii=False, indent=2)

    step_dir_p1 = runner._step_dir("phase_1")
    with open(step_dir_p1 / "phase1_style_preview.json", "w", encoding="utf-8") as f:
        json.dump(runner.phase1_clean, f, ensure_ascii=False, indent=2)

    if verbose:
        print(f"  ✓ Step 3.5: {'依赖图已构建' if runner.dep_graph else '依赖图构建失败'}")
        print(f"  ✓ Phase 1: {len(runner.phase1_clean['enemies'])} 敌人类型, {len(runner.phase1_clean['weapons'])} 武器类型")

    return f"Step 3.5+Phase 1 完成"


def _do_phase2_finalize(runner: InteractiveRunner, verbose: bool = True):
    """Phase 2: 精简标准化 → 重组装 → 验证 → 保存。"""
    if verbose:
        print("\n\033[1m[Phase 2] 精简标准化\033[0m")

    # 从 L2 提取实体
    step35_interactions = []
    step35_at = []
    for sdata in runner.l2_assembled.get("scenes", {}).values():
        step35_interactions.extend(sdata.get("interactions", []))
        step35_at.extend(sdata.get("auto_triggers", []))
    step35_events = runner.l2_assembled.get("events", [])

    # L2 descriptions
    l2_descriptions = {}
    for name, sdata in runner.l1_data.items():
        desc = sdata.get("description", "") or sdata.get("atmosphere", "")
        if desc:
            l2_descriptions[name] = desc

    # 技能名
    skill_names = []
    skill_path = PROJECT_ROOT / runner.config.skill_checks_path
    if skill_path.exists():
        with open(skill_path, "r", encoding="utf-8") as f:
            skill_checks = json.load(f)
            skill_names = sorted(set(s["name"] for s in skill_checks))

    stat_names = ["STR", "CON", "SIZ", "DEX", "APP", "INT", "POW", "EDU", "SAN", "HP", "LUCK", "MP"]

    prompt = build_step4_prompt(
        step35_interactions, step35_at, l2_descriptions,
        runner.l3_data.get("scene_intents", {}), runner.chapters,
        runner.phase1_clean, skill_names, stat_names,
    )
    step4 = runner.llm_json(prompt, system=STEP4_SYSTEM, call_name="phase2_standardize")

    p2_interactions = step4.get("interactions", step35_interactions)
    p2_auto_triggers = step4.get("auto_triggers", step35_at)
    runner.interactions = _merge_phase2_fields(step35_interactions, p2_interactions)
    runner.auto_triggers = _merge_phase2_fields(step35_at, p2_auto_triggers)

    # 去除 based_on
    for lst in (runner.interactions, runner.auto_triggers, runner.events):
        for e in lst:
            if isinstance(e, dict):
                e.pop("based_on", None)

    # 重新组装 L2
    runner.l2_assembled = _assemble_l2(
        runner.interactions, runner.events, runner.auto_triggers,
        runner.scene_movements, runner.l1_data,
        npc_profiles=runner.npc_profiles,
        boss_encounters=runner.l2_assembled.get("boss_encounters", []),
    )
    if runner.dep_graph:
        runner.l2_assembled["dependency_graph"] = runner.dep_graph.to_dict()
    runner.l2_assembled["_phase1"] = runner.phase1_clean

    # 保存 Phase 2
    step_dir = runner._step_dir("phase_2")
    with open(step_dir / "phase2_standardization.json", "w", encoding="utf-8") as f:
        json.dump(step4, f, ensure_ascii=False, indent=2)

    if verbose:
        print(f"  ✓ Phase 2 完成: @标记标准化")
        print(f"  ✓ L2 重新组装: {len(runner.l2_assembled.get('scenes',{}))} 场景")

    # ── 验证 ──
    if verbose:
        print("\n\033[1m[验证] Schema + 交叉引用\033[0m")

    schema_reports = validate_all(runner.l1_data, runner.l2_assembled, runner.l3_data)
    cross_ref = cross_validate_layers(
        runner.l1_data, runner.l2_assembled, runner.l3_data,
        weapon_lib=runner.wl, enemy_lib=runner.el,
    )

    with open(runner.output_dir / "_validation_report.json", "w", encoding="utf-8") as f:
        json.dump({
            "schema": {
                layer: {"errors": len(r.errors), "warnings": len(r.warnings), "is_valid": r.is_valid}
                for layer, r in schema_reports.items()
            },
            "cross_ref": {
                "errors": len(cross_ref.errors),
                "warnings": len(cross_ref.issues),
                "is_valid": cross_ref.is_valid,
            },
        }, f, ensure_ascii=False, indent=2)

    if verbose:
        for layer, r in schema_reports.items():
            status = "PASS" if r.is_valid else "ISSUES"
            print(f"  {layer} [{status}]: {r.summary()}")
        print(f"  交叉引用: {cross_ref.summary()}")

    # ── 保存最终产物 ──
    module_dir = PROJECT_ROOT / "data" / "modules" / runner.config.module_name
    module_dir.mkdir(parents=True, exist_ok=True)

    with open(module_dir / "l1_player.json", "w", encoding="utf-8") as f:
        json.dump(runner.l1_data, f, ensure_ascii=False, indent=2)
    with open(module_dir / "l2_keeper.json", "w", encoding="utf-8") as f:
        json.dump(runner.l2_assembled, f, ensure_ascii=False, indent=2)
    with open(module_dir / "l3_designer.json", "w", encoding="utf-8") as f:
        json.dump(runner.l3_data, f, ensure_ascii=False, indent=2)

    if verbose:
        print(f"\n  最终结果: {module_dir}/")
        print(f"    l1_player.json, l2_keeper.json, l3_designer.json")
        print(f"  调试产物: {runner.output_dir}/")

    # 保存配置快照
    runner.config.to_json(str(runner.output_dir / "config.json"))

    # 保存调用日志
    with open(runner.output_dir / "_pipeline_log.txt", "w", encoding="utf-8") as f:
        f.write(f"模型: json={runner.config.json_model}, text={runner.config.text_model}\n")
        f.write(f"思考: {runner.config.thinking_enabled}, 强度={runner.config.reasoning_effort}\n")
        f.write(f"温度: json={runner.config.json_temperature}, text={runner.config.text_temperature}\n")
        f.write(f"总 LLM 调用: {len(runner.llm_logger.call_log)}\n\n")
        for call in runner.llm_logger.call_log:
            f.write(f"  [{call['name']}] {call.get('model','')} | "
                    f"思考={'on' if call.get('thinking') else 'off'} | "
                    f"{call.get('elapsed_s',0)}s\n")

    return f"管线完成: {'PASS' if cross_ref.is_valid else 'HAS_ISSUES'}"


# ═══════════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════════

# 可跳过的步骤映射（start_from 使用）
_STEP_ORDER = ["step_1", "step_2a", "step_2bc", "step_3a", "step_3b", "step_35", "phase_2"]


def run_interactive(config: PipelineConfig):
    """手动步进模式：逐步执行，每步可暂停/重试/编辑/改配置。"""
    runner = InteractiveRunner(config)

    # ── 加载库 ──
    print("加载武器/敌人/Boss库...")
    wl = WeaponLibrary(); wl.load_core(str(PROJECT_ROOT / config.weapon_lib_path))
    el = EnemyLibrary(); el.load_core(str(PROJECT_ROOT / config.enemy_lib_path))
    bl = BossLibrary(str(PROJECT_ROOT / config.boss_lib_path))
    runner.wl = wl
    runner.el = el
    runner.bl = bl

    # ── 加载文档 ──
    docx_path = PROJECT_ROOT / config.docx_path
    if not docx_path.exists():
        print(f"错误：源文档不存在: {docx_path}")
        sys.exit(1)
    content = _load_document(str(docx_path))
    content = estimate_and_truncate_context(content)
    runner.content = content
    print(f"源文档: {docx_path.name} ({len(content)} 字符)")

    # 保存配置快照
    config.to_json(str(runner.output_dir / "config.json"))

    skip_until = config.start_from if config.start_from != "step_1" else None
    skip_mode = skip_until is not None

    if skip_mode:
        print(f"\n  断点续跑模式，跳过 {skip_until} 之前的步骤")
        print(f"  确保中间文件存在于: {runner.output_dir}")
        input("  按 Enter 继续...")

    # ── 步骤列表 ──
    steps = [
        ("step_1",    _do_step1),
        ("step_2a",   _do_step2a),
        ("step_2bc",  _do_step2bc),
        ("step_3a",   _do_step3a_25),
        ("step_3b",   _do_step3b),
        ("step_35",   _do_step35_phase1),
        ("phase_2",   _do_phase2_finalize),
    ]

    for step_name, step_fn in steps:
        if skip_mode:
            if step_name == skip_until:
                skip_mode = False
                print(f"\n  从 {step_name} 开始执行...")
            else:
                print(f"  [跳过] {step_name}")
                runner._completed_steps.add(step_name)
                continue

        # 重试循环
        while True:
            try:
                summary = step_fn(runner)
                runner._completed_steps.add(step_name)
                runner._interact(step_name, summary)
                break  # 用户确认继续
            except _RetryStep:
                print(f"\n  ↻ 重试 {step_name}...")
                continue
            except PipelineAborted:
                raise

    print()
    print("=" * 50)
    print("  管线执行完毕")
    print(f"  最终产物: data/modules/{config.module_name}/")
    print(f"  中间结果: {runner.output_dir.relative_to(PROJECT_ROOT)}")
    print(f"  总 LLM 调用: {len(runner.llm_logger.call_log)}")
    print("=" * 50)


def run_auto(config: PipelineConfig):
    """自动模式：复用与 interactive 相同的 _do_step* 函数，全程无交互。"""
    runner = InteractiveRunner(config)

    # ── 加载库 ──
    print("加载武器/敌人/Boss库...")
    wl = WeaponLibrary(); wl.load_core(str(PROJECT_ROOT / config.weapon_lib_path))
    el = EnemyLibrary(); el.load_core(str(PROJECT_ROOT / config.enemy_lib_path))
    bl = BossLibrary(str(PROJECT_ROOT / config.boss_lib_path))
    runner.wl = wl
    runner.el = el
    runner.bl = bl

    # ── 加载文档 ──
    docx_path = PROJECT_ROOT / config.docx_path
    if not docx_path.exists():
        print(f"错误：源文档不存在: {docx_path}")
        sys.exit(1)
    content = _load_document(str(docx_path))
    content = estimate_and_truncate_context(content)
    runner.content = content
    print(f"源文档: {docx_path.name} ({len(content)} 字符)")

    # 保存配置快照
    config.to_json(str(runner.output_dir / "config.json"))

    print(f"\n  自动模式 — 全流程执行")
    print(f"  JSON 模型: {config.json_model}, 思考: {config.thinking_enabled}/{config.reasoning_effort}")
    print(f"  输出目录: {runner.output_dir.relative_to(PROJECT_ROOT)}")
    print()

    # ── 步骤列表（与 interactive 模式完全一致）──
    steps = [
        ("step_1",    _do_step1),
        ("step_2a",   _do_step2a),
        ("step_2bc",  _do_step2bc),
        ("step_3a",   _do_step3a_25),
        ("step_3b",   _do_step3b),
        ("step_35",   _do_step35_phase1),
        ("phase_2",   _do_phase2_finalize),
    ]

    t0 = time.time()
    skip_mode = config.start_from != "step_1"
    for step_name, step_fn in steps:
        if skip_mode:
            if step_name == config.start_from:
                skip_mode = False
                print(f"  [续跑] 从 {step_name} 开始执行")
            else:
                print(f"  [跳过] {step_name}")
                runner._completed_steps.add(step_name)
                continue
        try:
            summary = step_fn(runner)
            runner._completed_steps.add(step_name)
        except Exception as e:
            print(f"\n  [错误] {step_name} 执行失败: {e}")
            import traceback
            traceback.print_exc()
            break

    elapsed = time.time() - t0

    # 保存调用日志
    with open(runner.output_dir / "_pipeline_log.txt", "w", encoding="utf-8") as f:
        f.write(f"模型: json={config.json_model}, text={config.text_model}\n")
        f.write(f"思考: {config.thinking_enabled}, 强度={config.reasoning_effort}\n")
        f.write(f"温度: json={config.json_temperature}, text={config.text_temperature}\n")
        f.write(f"总耗时: {elapsed:.1f}s\n")
        f.write(f"总 LLM 调用: {len(runner.llm_logger.call_log)}\n\n")
        for call in runner.llm_logger.call_log:
            f.write(f"  [{call['name']}] {call.get('model','')} | "
                    f"思考={'on' if call.get('thinking') else 'off'} | "
                    f"{call.get('elapsed_s',0)}s\n")

    print()
    print("=" * 50)
    print("  管线执行完毕")
    print(f"  最终产物: data/modules/{config.module_name}/")
    print(f"  中间结果: {runner.output_dir.relative_to(PROJECT_ROOT)}")
    print(f"  总耗时: {elapsed:.1f}s")
    print(f"  总 LLM 调用: {len(runner.llm_logger.call_log)}")
    print("=" * 50)


# ═══════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="TRPG 模组解析管线 — 将模组文档 (.docx/.pdf/.txt) 转换为 L1/L2/L3 JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run_pipeline.py                                交互式向导 → 手动步进
  python run_pipeline.py --auto --docx 常暗之厢.docx    自动全流程
  python run_pipeline.py --config config.json            从配置文件运行
  python run_pipeline.py --start-from step_3a --config cfg.json   断点续跑
        """,
    )
    parser.add_argument("--auto", action="store_true",
                        help="自动模式（全流程无交互）")
    parser.add_argument("--config", type=str,
                        help="配置文件路径 (JSON)")
    parser.add_argument("--docx", type=str,
                        help="源文档路径 .docx/.pdf/.txt（覆盖配置文件中的值）")
    parser.add_argument("--module", type=str,
                        help="模组名称（覆盖配置文件中的值）")
    parser.add_argument("--start-from", type=str,
                        choices=VALID_START_FROM,
                        help="断点续跑起始步骤")
    parser.add_argument("--model", type=str,
                        choices=VALID_MODELS,
                        help="LLM 模型（覆盖配置文件，JSON 和文本模式同时设置）")
    parser.add_argument("--thinking-off", action="store_true",
                        help="关闭思考模式")
    parser.add_argument("--weapon-lib", type=str,
                        help="武器库 JSON 路径（覆盖默认值）")
    parser.add_argument("--enemy-lib", type=str,
                        help="敌人库 JSON 路径（覆盖默认值）")
    parser.add_argument("--boss-lib", type=str,
                        help="Boss 库 JSON 路径（覆盖默认值）")

    args = parser.parse_args()

    # ── 加载配置 ──
    if args.config:
        if not os.path.exists(args.config):
            print(f"错误：配置文件不存在: {args.config}")
            sys.exit(1)
        config = PipelineConfig.from_json(args.config)
        print(f"配置已加载: {args.config}")
    elif args.auto:
        # 自动模式必须提供 docx
        if not args.docx:
            print("错误：自动模式需要 --docx <路径>")
            sys.exit(1)
        config = PipelineConfig(docx_path=args.docx, auto_mode=True)
    else:
        # 交互式向导
        config = PipelineConfig.from_wizard()

    # ── 命令行覆盖 ──
    if args.docx:
        config.docx_path = args.docx
    if args.module:
        config.module_name = args.module
    if args.auto:
        config.auto_mode = True
    if args.start_from:
        config.start_from = args.start_from
    if args.model:
        config.json_model = args.model
        config.text_model = args.model
    if args.thinking_off:
        config.thinking_enabled = False
    if args.weapon_lib:
        config.weapon_lib_path = args.weapon_lib
    if args.enemy_lib:
        config.enemy_lib_path = args.enemy_lib
    if args.boss_lib:
        config.boss_lib_path = args.boss_lib

    # ── 推断模组名 ──
    if not config.module_name and config.docx_path:
        # 从 docx 文件名推断：去掉路径和扩展名
        stem = Path(config.docx_path).stem
        # 去掉括号中的规则信息
        import re
        stem = re.sub(r'[（(][^)）]*[)）]', '', stem).strip()
        config.module_name = stem
        print(f"模组名推断: {config.module_name}")

    # ── 验证 ──
    if not config.docx_path:
        print("错误：必须指定源 .docx 路径")
        sys.exit(1)

    if config.json_model not in VALID_MODELS:
        print(f"错误：无效 JSON 模型 '{config.json_model}'。有效值: {', '.join(VALID_MODELS)}")
        sys.exit(1)

    if config.text_model not in VALID_MODELS:
        print(f"错误：无效文本模型 '{config.text_model}'。有效值: {', '.join(VALID_MODELS)}")
        sys.exit(1)

    if config.reasoning_effort not in VALID_REASONING_EFFORT:
        print(f"错误：无效推理强度 '{config.reasoning_effort}'。有效值: {', '.join(VALID_REASONING_EFFORT)}")
        sys.exit(1)

    if not (0.0 <= config.json_temperature <= 1.0):
        print(f"错误：JSON 温度必须在 0.0-1.0 之间")
        sys.exit(1)

    if not (0.0 <= config.text_temperature <= 1.0):
        print(f"错误：文本温度必须在 0.0-1.0 之间")
        sys.exit(1)

    # ── 执行 ──
    try:
        if config.auto_mode:
            run_auto(config)
        else:
            run_interactive(config)
    except PipelineAborted:
        print("\n管线已中止。")
        sys.exit(0)
    except KeyboardInterrupt:
        print("\n\n用户中断。")
        sys.exit(0)
    except Exception as e:
        print(f"\n管线异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
