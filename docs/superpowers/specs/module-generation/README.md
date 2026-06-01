# 模组生成 — Spec 索引

离线流程：原始模组文档 → 三层 JSON → 游戏循环可消费。

## 核心文档

| 文档 | 内容 | 状态 |
|------|------|------|
| [`../2026-05-13-parser-system-overhaul-design.md`](../2026-05-13-parser-system-overhaul-design.md) | 架构设计：三层模型、武器/敌人库、双层判定、内容注入、Game Loop 适配 | 设计完成 |
| [`../2026-05-13-three-layer-schema-overview.md`](../2026-05-13-three-layer-schema-overview.md) | L1/L2/L3 字段级 Schema 定义 + 层间引用关系 | 设计完成，L3 模板已由用户手动精简 |
| [`../2026-05-13-layered-data-flow.md`](../2026-05-13-layered-data-flow.md) | **主文档** — 全景数据流、文件关系、当前实现细节、四步渐进式流程提案 | 持续更新 |

## 实现状态

| 模块 | 文件 | 状态 |
|------|------|------|
| 武器/敌人库 | `src/library/` (weapons, enemies, judgment, injector) | ✓ 已实现 |
| 三层数据模型 | `src/module_designer/` (l1_player, l2_keeper, l3_designer) | ✓ 已实现 |
| Schema 验证 | `src/module_designer/layered_schema.py` | ✓ 已实现 |
| LLM 解析器 | `src/module_designer/layered_parser.py` | ✓ **已重写** (四步渐进式 + 保底策略) |
| 后处理管线 | `src/module_designer/layered_pipeline.py` | ✓ **已重写** (并行编排 + retry/fallback) |

## 下一步重点

**生成端已完成。** 下一步聚焦消费端 P0 断点：
1. Interaction 添加 skill_name/difficulty 字段
2. 接通 L1/L3 加载路径
3. 清理死代码 (_check_deviation, EncounterAnchor)
4. 实现 auto_trigger 运行时条件解析
