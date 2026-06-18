# GitHub 上传前清理设计

**日期**: 2026-06-18
**状态**: 已批准

## 1. requirements.txt

删除 3 个废弃依赖（ragas_evaluator.py 已删除）：
- `ragas>=0.4.3`
- `datasets>=2.14.0`
- `instructor>=1.0.0`

## 2. .gitignore

新增 6 条忽略规则：
- `.browsers/` — 浏览器自动化缓存（Chromium ~300MB）
- `.claude/` — Claude Code 配置目录
- `code-review/` — 一次性 Code Review HTML 产物
- `milvus/` — 独立 Milvus docker-compose（项目用根目录的）
- `frontend/e2e/` — Playwright E2E 测试
- `frontend/test-results/` — Playwright 测试结果

## 3. .dockerignore

新增 3 条：
- `.browsers/`
- `code-review/`
- `milvus/`

## 4. README.md

更新 3 处：
- 项目结构：删除 `ragas_evaluator.py`，新增 `metrics/`, `unified_evaluator.py`, `report.py`, `router/`, `strategy/`
- 技术栈：RAGAS → 统一评测框架
- API 表：`/admin/ragas` → `/admin/evaluate/run`