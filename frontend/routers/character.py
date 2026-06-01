"""frontend/routers/character.py — Character creation wizard API."""
from __future__ import annotations

import json
import random
import uuid
from pathlib import Path
from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, PlainTextResponse, Response, JSONResponse

from frontend._paths import PROJECT_ROOT, FRONTEND_DIR

router = APIRouter(prefix="/character", tags=["character"])

TEMPLATES_DIR = FRONTEND_DIR / "templates"
UPLOADS_DIR = FRONTEND_DIR / "static" / "uploads"

from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ── Skill base values (COC 7th) ──
SKILLS = [
    {"name": "会计", "base": 5, "cat": "知识"}, {"name": "人类学", "base": 1, "cat": "知识"},
    {"name": "估价", "base": 5, "cat": "知识"}, {"name": "考古学", "base": 1, "cat": "知识"},
    {"name": "魅惑", "base": 15, "cat": "社交"}, {"name": "攀爬", "base": 20, "cat": "操作"},
    {"name": "信用评级", "base": 0, "cat": "社交"}, {"name": "克苏鲁神话", "base": 0, "cat": "知识"},
    {"name": "乔装", "base": 5, "cat": "社交"}, {"name": "汽车驾驶", "base": 20, "cat": "操作"},
    {"name": "电气维修", "base": 10, "cat": "操作"}, {"name": "电子学", "base": 1, "cat": "知识"},
    {"name": "话术", "base": 5, "cat": "社交"}, {"name": "格斗", "base": 25, "cat": "战斗"},
    {"name": "枪械", "base": 20, "cat": "战斗"}, {"name": "急救", "base": 30, "cat": "操作"},
    {"name": "历史", "base": 5, "cat": "知识"}, {"name": "恐吓", "base": 15, "cat": "社交"},
    {"name": "跳跃", "base": 20, "cat": "操作"}, {"name": "外语", "base": 1, "cat": "知识"},
    {"name": "母语", "base": 50, "cat": "知识"}, {"name": "法律", "base": 5, "cat": "知识"},
    {"name": "图书馆使用", "base": 20, "cat": "知识"}, {"name": "聆听", "base": 20, "cat": "感知"},
    {"name": "锁匠", "base": 1, "cat": "操作"}, {"name": "机械维修", "base": 10, "cat": "操作"},
    {"name": "医学", "base": 1, "cat": "知识"}, {"name": "博物学", "base": 10, "cat": "知识"},
    {"name": "导航", "base": 10, "cat": "知识"}, {"name": "神秘学", "base": 5, "cat": "知识"},
    {"name": "操作重型机械", "base": 1, "cat": "操作"}, {"name": "说服", "base": 10, "cat": "社交"},
    {"name": "驾驶", "base": 20, "cat": "操作"}, {"name": "心理学", "base": 10, "cat": "感知"},
    {"name": "精神分析", "base": 1, "cat": "知识"}, {"name": "骑术", "base": 5, "cat": "操作"},
    {"name": "科学", "base": 1, "cat": "知识"}, {"name": "妙手", "base": 10, "cat": "操作"},
    {"name": "潜行", "base": 20, "cat": "操作"}, {"name": "侦查", "base": 25, "cat": "感知"},
    {"name": "生存", "base": 10, "cat": "操作"}, {"name": "游泳", "base": 20, "cat": "操作"},
    {"name": "投掷", "base": 20, "cat": "战斗"}, {"name": "追踪", "base": 10, "cat": "感知"},
]

STATS = ["STR", "CON", "SIZ", "DEX", "APP", "INT", "POW", "EDU", "LUCK"]
STAT_LABELS = {"STR": "力量", "CON": "体质", "SIZ": "体型", "DEX": "敏捷", "APP": "外貌",
               "INT": "智力", "POW": "意志", "EDU": "教育", "LUCK": "幸运"}
STAT_ROLLS = {
    "STR": (3, 0), "CON": (3, 0), "DEX": (3, 0), "APP": (3, 0), "POW": (3, 0),
    "SIZ": (2, 6), "INT": (2, 6), "EDU": (2, 6), "LUCK": (3, 0),
}


def _load_occupations():
    path = PROJECT_ROOT / "data" / "occupations.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return []


def _roll_stat(dice: int, add: int) -> int:
    return (sum(random.randint(1, 6) for _ in range(dice)) + add) * 5


@router.get("", response_class=HTMLResponse)
async def character_page(request: Request):
    return templates.TemplateResponse(request, "character.html", {
        "skills": SKILLS,
        "stats": STATS,
        "stat_labels": STAT_LABELS,
        "occupations": _load_occupations(),
    })


@router.post("/upload-avatar")
async def upload_avatar(file: UploadFile = File(...)):
    ext = Path(file.filename).suffix if file.filename else ".png"
    if ext.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        return JSONResponse({"error": "不支持的文件格式"}, status_code=400)
    filename = f"avatar_{uuid.uuid4().hex}{ext}"
    dest = UPLOADS_DIR / "avatars" / filename
    content = await file.read()
    dest.write_bytes(content)
    url = f"/static/uploads/avatars/{filename}"
    return JSONResponse({"url": url})


@router.get("/step/{n}", response_class=HTMLResponse)
async def step_partial(request: Request, n: int):
    if n == 1:
        return templates.TemplateResponse(request, "partials/char-step1.html", {
            "stats": STATS, "stat_labels": STAT_LABELS, "stat_rolls": STAT_ROLLS,
        })
    elif n == 2:
        return templates.TemplateResponse(request, "partials/char-step2.html", {
            "skills": SKILLS, "occupations": _load_occupations(),
        })
    elif n == 3:
        return templates.TemplateResponse(request, "partials/char-step3.html", {})
    return HTMLResponse("<p class='text-red-500'>Invalid step</p>", status_code=404)


@router.post("/roll", response_class=HTMLResponse)
async def roll_stats():
    import random as _r
    values = {s: _roll_stat(*STAT_ROLLS[s]) for s in STATS}
    hp = (values["CON"] + values["SIZ"]) // 10
    mp = values["POW"] // 5
    san = values["POW"]
    dodge = values["DEX"] // 2
    ss = values["STR"] + values["SIZ"]
    if ss <= 64: db, build = "-2", -2
    elif ss <= 84: db, build = "-1", -1
    elif ss <= 124: db, build = "0", 0
    elif ss <= 164: db, build = "+1D4", 1
    elif ss <= 204: db, build = "+1D6", 2
    else: db, build = "+2D6", 3

    cells = "".join(
        f'<div class="stat-card p-3 bg-[#1a150c] border border-[#3a2810] rounded text-center">'
        f'<div class="text-xs text-gray-500">{STAT_LABELS[s]} ({s})</div>'
        f'<input type="number" name="stat_{s}" value="{values[s]}" min="8" max="99" '
        f'class="stat-input w-16 text-xl font-bold text-aged-gold bg-transparent border-b border-gray-700 text-center focus:outline-none focus:border-aged-gold [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none" '
        f'onchange="charRecalcDerived();charStoreStats()" oninput="charRecalcDerived()">'
        f'</div>'
        for s in STATS
    )
    derived = (
        f'<div id="derived-stats" class="grid grid-cols-3 gap-1 text-xs mt-2 text-gray-500">'
        f'<div>HP <input type="number" id="derived-hp" name="stat_HP" value="{hp}" readonly min="1" max="99" class="derived-input w-12 bg-transparent border-0 text-center text-green-400 font-bold focus:outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none" tabindex="-1"></div>'
        f'<div>MP <input type="number" id="derived-mp" name="stat_MP" value="{mp}" readonly min="0" max="99" class="derived-input w-12 bg-transparent border-0 text-center text-gray-200 font-bold focus:outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none" tabindex="-1"></div>'
        f'<div>SAN <input type="number" id="derived-san" name="stat_SAN" value="{san}" readonly min="0" max="99" class="derived-input w-12 bg-transparent border-0 text-center text-aged-gold font-bold focus:outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none" tabindex="-1"></div>'
        f'<div>DODGE <input type="number" id="derived-dodge" name="stat_DODGE" value="{dodge}" readonly min="1" max="99" class="derived-input w-12 bg-transparent border-0 text-center text-gray-300 font-bold focus:outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none" tabindex="-1"></div>'
        f'<div>DB <input type="text" id="derived-db" name="stat_DB" value="{db}" readonly class="derived-input w-12 bg-transparent border-0 text-center text-gray-300 font-bold focus:outline-none" tabindex="-1"></div>'
        f'<div>BUILD <input type="number" id="derived-build" name="stat_BUILD" value="{build}" readonly min="-2" max="6" class="derived-input w-12 bg-transparent border-0 text-center text-gray-300 font-bold focus:outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none" tabindex="-1"></div>'
        f'</div>'
    )
    return HTMLResponse(f'<div class="grid grid-cols-3 gap-3">{cells}</div><div class="mt-4 p-3 bg-[#1a150c] border border-[#3a2810] rounded">{derived}</div>')


@router.get("/skills-list", response_class=HTMLResponse)
async def skills_list(occupation: str = ""):
    occs = _load_occupations()
    occ = None
    occ_skill_names = set()
    if occupation:
        occs_match = [o for o in occs if o["name"] == occupation]
        if occs_match:
            occ = occs_match[0]
            occ_skill_names = set(occ.get("occupation_skills", []))

    pts_formula = occ.get("skill_points_formula", "—") if occ else "—"
    cr_min, cr_max = occ.get("credit_rating_min", 0) if occ else 0, occ.get("credit_rating_max", 99) if occ else 99

    # Group skills by category
    cats = {}
    for s in SKILLS:
        cats.setdefault(s["cat"], []).append(s)
    cat_order = ["战斗", "操作", "感知", "知识", "社交"]

    rows = []
    rows.append(f'<div class="text-sm text-gray-500 mb-2">职业技能点公式: {pts_formula} | 兴趣点: INT×2'
                f' | 信用评级范围: {cr_min}-{cr_max}</div>')
    if not occupation:
        rows.append('<div class="text-xs text-gray-600 mb-3">请先选择职业以查看技能优势</div>')

    for cat in cat_order:
        cat_skills = cats.get(cat, [])
        if not cat_skills:
            continue
        rows.append(f'<div class="text-xs text-gray-500 font-bold mt-3 mb-1 border-b border-gray-800 pb-1">{cat}</div>')
        for s in cat_skills:
            name = s["name"]
            base = s["base"]
            is_occ = name in occ_skill_names
            border_cls = "border-aged-gold" if is_occ else "border-[#4a3820]"
            bg_cls = "bg-aged-brown/20" if is_occ else "bg-[#1a150c]"
            badge = '<span class="text-[10px] text-aged-gold bg-aged-brown/30 px-1 rounded">职业</span>' if is_occ else ''
            rows.append(
                f'<div class="flex items-center gap-2 py-1 px-2 {bg_cls} rounded">'
                f'<span class="text-sm text-gray-300 w-32">{name} {badge}</span>'
                f'<span class="text-xs text-gray-600 w-16">基础 {base}%</span>'
                f'<input type="number" min="0" max="99" value="{base}" '
                f'class="skill-input w-16 bg-[#1a150c] border {border_cls} rounded px-2 py-1 text-xs text-gray-300 focus:border-aged-gold focus:outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none">'
                f'</div>'
            )

    html = "".join(rows)
    if html:
        html += (
            '<script>'
            'setTimeout(function(){'
            '  var saved = document.getElementById("skills-json")?.value;'
            '  if (saved) {'
            '    try { var obj = JSON.parse(saved);'
            '      document.querySelectorAll("#skills-list .skill-input").forEach(function(inp){'
            '        var label = inp.closest(".flex")?.querySelector("span")?.textContent?.replace(/职业\\s*$/,"").trim();'
            '        if (label && obj[label] !== undefined) inp.value = obj[label];'
            '      });'
            '    } catch(e) {}'
            '  }'
            '  charStoreSkills();'
            '}, 200);'
            '</script>'
        )
    return HTMLResponse(html)


@router.post("/generate-description")
async def generate_description(type: str = Form(...), prompt: str = Form(...)):
    from llm import call_deepseek
    if type == "appearance":
        system = "你是一个COC 7th TRPG角色外貌描述生成器。根据用户提供的关键词生成一段简洁的外貌描述（150字以内）。仅输出描述文本。"
    else:
        system = "你是一个COC 7th TRPG角色个人描述生成器。根据用户提供的关键词生成一段简洁的角色个人描述（150字以内）。仅输出描述文本。"
    try:
        result = call_deepseek(prompt, json_mode=False, system=system,
                              model="deepseek-v4-flash", thinking=False,
                              max_tokens=300, temperature=0.7, max_retries=1)
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(str(result).strip())
    except Exception as e:
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(f"[生成失败: {e}]", status_code=500)


def _build_export(name: str, age: int, gender: str,
                  occupation: str, appearance: str, description: str,
                  backstory: str,
                  stat_STR: int, stat_CON: int, stat_SIZ: int,
                  stat_DEX: int, stat_APP: int, stat_INT: int,
                  stat_POW: int, stat_EDU: int, stat_LUCK: int,
                  stat_HP: int, stat_MP: int, stat_SAN: int,
                  stat_DODGE: int, stat_DB: str, stat_BUILD: int,
                  skills_json: str, avatar_url: str):
    import json as _json
    from datetime import datetime as _dt
    from investigator.models import Stats, DerivedStats, Occupation
    from investigator.serialization import to_dict
    from investigator import Investigator
    from investigator.rules import create_skill_list

    inv = Investigator(name=name or "调查员", age=age, gender=gender or "男")
    inv.stats = Stats(
        STR=stat_STR, CON=stat_CON, SIZ=stat_SIZ, DEX=stat_DEX,
        APP=stat_APP, INT=stat_INT, POW=stat_POW, EDU=stat_EDU, LUCK=stat_LUCK,
    )
    inv.derived = DerivedStats(
        HP=stat_HP, HP_MAX=stat_HP, MP=stat_MP, SAN=stat_SAN, MOV=8,
        DB=stat_DB, BUILD=stat_BUILD, DODGE=stat_DODGE,
    )
    skills = create_skill_list()
    custom = _json.loads(skills_json) if skills_json.strip() else {}
    for s in skills:
        if s.name in custom:
            s.value = int(custom[s.name])
    inv.skills = skills
    inv.occupation = None
    for _occ in _load_occupations():
        if _occ["name"] == occupation:
            inv.occupation = Occupation(
                name=_occ["name"], description=_occ.get("description", ""),
                occupation_skills=_occ.get("occupation_skills", []),
            )
            break
    inv.appearance = appearance or ""
    inv.description = description or ""
    inv.backstory = backstory or ""
    inv.avatar_url = avatar_url or ""

    data = to_dict(inv)
    data["meta"].update({
        "version": "1.0",
        "created_at": _dt.now().isoformat(),
        "rules_edition": "COC7",
    })
    content = _json.dumps(data, ensure_ascii=False, indent=2)

    import zipfile, io
    from urllib.parse import quote
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('character.json', content)
        if inv.avatar_url and inv.avatar_url.startswith('/static/uploads/avatars/'):
            avatar_path = PROJECT_ROOT / 'frontend' / 'static' / 'uploads' / 'avatars' / Path(inv.avatar_url).name
            if avatar_path.exists():
                zf.write(avatar_path, f'avatar{avatar_path.suffix}')

    buf.seek(0)
    safe_name = (name or "character").strip()
    encoded = quote(f"{safe_name}.zip", safe="")
    from fastapi.responses import Response
    return Response(content=buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"})


@router.get("/export")
async def export_character_get(
    name: str = "", age: int = 20, gender: str = "",
    occupation: str = "", appearance: str = "", description: str = "",
    backstory: str = "",
    stat_STR: int = 0, stat_CON: int = 0, stat_SIZ: int = 0,
    stat_DEX: int = 0, stat_APP: int = 0, stat_INT: int = 0,
    stat_POW: int = 0, stat_EDU: int = 0, stat_LUCK: int = 0,
    stat_HP: int = 0, stat_MP: int = 0, stat_SAN: int = 0,
    stat_DODGE: int = 0, stat_DB: str = "0", stat_BUILD: int = 0,
    skills_json: str = "{}", avatar_url: str = "",
):
    return _build_export(name, age, gender, occupation, appearance, description,
                         backstory, stat_STR, stat_CON, stat_SIZ, stat_DEX,
                         stat_APP, stat_INT, stat_POW, stat_EDU, stat_LUCK,
                         stat_HP, stat_MP, stat_SAN, stat_DODGE, stat_DB,
                         stat_BUILD, skills_json, avatar_url)


@router.post("/export")
async def export_character(
    name: str = Form(""), age: int = Form(20), gender: str = Form(""),
    occupation: str = Form(""), appearance: str = Form(""),
    description: str = Form(""), backstory: str = Form(""),
    stat_STR: int = Form(0), stat_CON: int = Form(0), stat_SIZ: int = Form(0),
    stat_DEX: int = Form(0), stat_APP: int = Form(0), stat_INT: int = Form(0),
    stat_POW: int = Form(0), stat_EDU: int = Form(0), stat_LUCK: int = Form(0),
    stat_HP: int = Form(0), stat_MP: int = Form(0), stat_SAN: int = Form(0),
    stat_DODGE: int = Form(0), stat_DB: str = Form("0"), stat_BUILD: int = Form(0),
    skills_json: str = Form("{}"),
    avatar_url: str = Form(""),
):
    return _build_export(name, age, gender, occupation, appearance, description,
                         backstory, stat_STR, stat_CON, stat_SIZ, stat_DEX,
                         stat_APP, stat_INT, stat_POW, stat_EDU, stat_LUCK,
                         stat_HP, stat_MP, stat_SAN, stat_DODGE, stat_DB,
                         stat_BUILD, skills_json, avatar_url)
