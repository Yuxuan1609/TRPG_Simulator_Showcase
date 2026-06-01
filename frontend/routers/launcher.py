"""frontend/routers/launcher.py — Launcher page: module gen wizard + config + navigation."""
from __future__ import annotations

import json
from pathlib import Path
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, PlainTextResponse

from frontend._paths import PROJECT_ROOT, FRONTEND_DIR

router = APIRouter(tags=["launcher"])

TEMPLATES_DIR = FRONTEND_DIR / "templates"

from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

DEFAULT_CONFIG = {
    "model": "deepseek-v4-pro",
    "thinking": True,
    "reasoning_effort": "high",
    "flash_model": "deepseek-v4-flash",
    "llm_timeout_ms": 120000,
    "llm_slow_threshold_ms": 30000,
    "combat_llm_enhancement": False,
    "debug_mode": False,
}


def _config_path() -> Path:
    return PROJECT_ROOT / "config.json"


def _load_config() -> dict:
    cp = _config_path()
    if cp.exists():
        return json.loads(cp.read_text(encoding="utf-8"))
    return dict(DEFAULT_CONFIG)


def _save_config(data: dict) -> None:
    _config_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@router.get("/", response_class=HTMLResponse)
async def launcher_page(request: Request):
    config = _load_config()
    return templates.TemplateResponse(request, "launcher.html", {
        "config": config,
    })


@router.get("/launcher/tabs/{tab}", response_class=HTMLResponse)
async def launcher_tab(request: Request, tab: str):
    config = _load_config()
    if tab == "module-gen":
        return templates.TemplateResponse(request, "partials/launcher-module-gen.html", {})
    elif tab == "step0":
        return templates.TemplateResponse(request, "partials/launcher-step0.html", {})
    elif tab == "game-start":
        return templates.TemplateResponse(request, "partials/launcher-game-start.html", {})
    elif tab == "config":
        return templates.TemplateResponse(request, "partials/launcher-config.html", {
            "config": config,
        })
    return HTMLResponse("<p class='text-red-500'>Unknown tab</p>", status_code=404)


@router.post("/api/config/save")
async def save_config(
    model: str = Form(...),
    thinking: str = Form("off"),
    reasoning_effort: str = Form("high"),
    flash_model: str = Form("deepseek-v4-flash"),
    llm_timeout_ms: int = Form(120000),
    llm_slow_threshold_ms: int = Form(30000),
    combat_llm_enhancement: str = Form("off"),
    debug_mode: str = Form("off"),
):
    data = {
        "model": model,
        "thinking": thinking == "on",
        "reasoning_effort": reasoning_effort,
        "flash_model": flash_model,
        "llm_timeout_ms": llm_timeout_ms,
        "llm_slow_threshold_ms": llm_slow_threshold_ms,
        "combat_llm_enhancement": combat_llm_enhancement == "on",
        "debug_mode": debug_mode == "on",
    }
    _save_config(data)
    return PlainTextResponse("配置已保存 ✓")


@router.get("/api/config/load")
async def load_config():
    return _load_config()


@router.post("/api/step0/start")
async def start_step0(
    source: str = Form(...),
    module_name: str = Form(...),
):
    """Run Step 0: novel → module document. Step 0 is always executed separately from the pipeline."""
    import subprocess
    import sys
    import threading

    source_path = PROJECT_ROOT / source
    if not source_path.exists():
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(f"源文件不存在: {source}", status_code=400)

    output_path = PROJECT_ROOT / "data" / "modules" / module_name / "module_step0.txt"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, str(PROJECT_ROOT / "run_step0.py"),
        str(source_path),
        str(output_path),
    ]

    def run_step0():
        subprocess.run(cmd, cwd=str(PROJECT_ROOT))

    thread = threading.Thread(target=run_step0, daemon=True)
    thread.start()

    from fastapi.responses import HTMLResponse
    return HTMLResponse(
        '<div class="text-sm text-aged-gold mt-4">'
        f'  <p>✓ Step 0 已启动 — 模组: {module_name}</p>'
        f'  <p class="text-xs text-gray-500 mt-1">输出: data/modules/{module_name}/module_step0.txt</p>'
        f'  <p class="text-xs text-gray-500">可在控制台查看进度输出</p>'
        '</div>'
    )


@router.post("/api/pipeline/start")
async def start_pipeline(
    source: str = Form(...),
    module_name: str = Form(...),
    output_dir: str = Form("data/modules/"),
    start_from: str = Form("step_1"),
    weapon_path: str = Form(""),
    enemy_path: str = Form(""),
    boss_path: str = Form(""),
):
    import subprocess
    import sys
    import threading

    source_path = PROJECT_ROOT / source
    if not source_path.exists():
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(f"源文件不存在: {source}", status_code=400)

    cmd = [
        sys.executable, str(PROJECT_ROOT / "run_pipeline.py"),
        "--auto",
        "--docx", str(source_path),
        "--module", module_name,
        "--start-from", start_from,
    ]
    if weapon_path:
        cmd += ["--weapon-lib", weapon_path]
    if enemy_path:
        cmd += ["--enemy-lib", enemy_path]
    if boss_path:
        cmd += ["--boss-lib", boss_path]
    def run_pipeline():
        subprocess.run(cmd, cwd=str(PROJECT_ROOT))

    thread = threading.Thread(target=run_pipeline, daemon=True)
    thread.start()

    from fastapi.responses import HTMLResponse
    return HTMLResponse(
        '<div class="text-sm text-aged-gold mt-4">'
        f'  <p>✓ 管线已启动 — 模组: {module_name}</p>'
        f'  <p class="text-xs text-gray-500 mt-1">输出目录: {output_dir}</p>'
        f'  <p class="text-xs text-gray-500">可在控制台查看进度输出</p>'
        '</div>'
    )


@router.post("/api/pipeline/validate")
async def validate_pipeline(
    source: str = Form(""),
    module_name: str = Form(""),
    output_dir: str = Form(""),
    start_from: str = Form(""),
):
    """Validate intermediate files exist for pipeline resume at given step."""
    import os as _os

    if not start_from:
        if source and not _os.path.exists(str(PROJECT_ROOT / source)):
            return HTMLResponse(
                f'<span class="text-red-400">源文件不存在: {source}</span>'
            )
        return HTMLResponse(
            '<span class="text-coc-green">将从 Step 1a 开始完整生成</span>'
        )

    mod_dir = output_dir or f"data/modules/{module_name}"

    required = {
        "step_2a": [f"{mod_dir}/module_step0.txt"],
        "step_3a": [f"{mod_dir}/module_step0.txt", f"{mod_dir}/l2_keeper.json"],
        "step_3b": [f"{mod_dir}/l2_keeper.json", f"{mod_dir}/l1_player.json", f"{mod_dir}/l3_designer.json"],
    }

    files_needed = required.get(start_from, [])
    if not files_needed:
        return HTMLResponse('<span class="text-gray-400">未知步骤</span>')

    missing = [f for f in files_needed if not _os.path.exists(str(PROJECT_ROOT / f))]
    if missing:
        names = ", ".join(missing)
        return HTMLResponse(
            f'<span class="text-red-400">缺少文件: {names}</span>'
        )

    import json as _json
    for f in files_needed:
        fp = PROJECT_ROOT / f
        if fp.suffix == ".json" and fp.exists():
            try:
                _json.loads(fp.read_text(encoding="utf-8"))
            except Exception:
                return HTMLResponse(
                    f'<span class="text-red-400">JSON 格式错误: {f}</span>'
                )

    return HTMLResponse(
        '<span class="text-coc-green">所有必需文件已就绪，可以续跑</span>'
    )
