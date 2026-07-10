# L03 空心 Bank 清理 — 详细实施方案

> 调查日期：2026-07-09
> 数据源：Hindsight API（http://localhost:8888）+ 代码分析（retrieval.py / banks.py / documents.py / upload.py / query.py）+ kb-web DB

---

## 一、12 个 Bank 状态总表

### 1.1 Hindsight 注册状态

| # | bank_id | fact_count | 最后写入时间(UTC) | 创建时间(UTC) | 状态判定 |
|---|---------|-----------|-------------------|--------------|---------|
| 1 | `kb_general` | **6,710** | 2026-07-08 15:32 | 2026-06-05 | ✅ 活跃 — 综合文件、商业分析、方法论共用 |
| 2 | `kb_standard` | **10,346** | 2026-07-01 06:36 | 2026-06-05 | ✅ 活跃 — 规范标准主库 |
| 3 | `kb_checklist` | **4,434** | 2026-06-19 17:33 | 2026-06-07 | ✅ 活跃 — 检查标准 |
| 4 | `kb` | **2,838** | 2026-07-02 15:44 | 2026-06-07 | ⚠️ 活跃但冗余 — 旧聚合库，被 `kb_general/standard/industry` 替代 |
| 5 | `kb_industry` | **1,812** | 2026-07-01 11:47 | 2026-06-05 | ✅ 活跃 — 信息化行业文档 |
| 6 | `kb_project` | **699** | 2026-06-24 14:43 | 2026-06-05 | ✅ 活跃 — 项目资料 |
| 7 | `kb_tech` | **407** | 2026-06-24 15:24 | 2026-06-06 | ✅ 活跃 — 技术指导书 |
| 8 | `general` | **50** | 2026-06-02 11:13 | 2026-06-01 | 🔴 空心 — 被 `kb_general` 替代，无文档引用 |
| 9 | `kb_xhs` | **1** | 2026-07-08 09:55 | 2026-06-24 | ✅ 活跃（新库，数据少但持续写入中） |
| 10 | `kb_standards` | **0** | 2026-06-30 23:09 | 2026-06-30 | 🔴 空心重复 — `kb_standard` 的重复空库 |
| 11 | `industry_docs` | **0** | 2026-06-30 04:46 | 2026-06-30 | 🔴 空心重复 — `kb_industry` 的重复空库 |
| 12 | `default` | **0** | 2026-06-30 03:24 | 2026-06-30 | 🔴 空心孤儿 — 未在任何配置中被引用 |

### 1.2 前端 Bank 配置 → Hindsight 映射（`retrieval.py:33-45`）

| 前端 Key | 显示名 | hindsight bank | 状态 |
|----------|-------|---------------|------|
| `all` | 全部 | None（聚合查询所有 active banks） | ✅ |
| `standards` | 规范 | `kb_standard` | ✅ |
| `project_docs` | 项目资料 | `kb_project` | ✅ |
| `industry_docs` | 信息化行业文档 | `kb_industry` | ✅ |
| `general` | 综合文件 | `kb_general` | ✅ |
| `checklist` | 检查标准 | `kb_checklist` | ✅ |
| `xhs` | 小红书技术 | `kb_xhs` | ✅ |
| `business` | 商业分析 | `kb_general` | ✅（共享） |
| `methodology` | 方法论 | `kb_general` | ✅（共享） |
| `tech_guides` | 技术指导书 | `kb_tech` | ✅ |
| `templates` | 方案模板 | ❌ `kb_template` **不存在于 Hindsight** | ⚠️ 悬空引用 |

### 1.3 DB 文档→hs_bank 分布（kb-web DB）

| hs_bank | 文档数 | 说明 |
|---------|--------|------|
| `kb_standard` | 174 | 规范标准文档 |
| `kb_general` | 95 | 综合 + 商业 + 方法论文档 |
| `kb_xhs` | 16 | 小红书技术文档 |
| `kb_industry` | 15 | 行业文档 |
| `kb_project` | 6 | 项目资料 |
| `kb_tech` | 2 | 技术指导书 |
| `kb_checklist` | 1 | 检查标准 |

确认：**没有任何 DB 文档引用以下 hs_bank**：`kb`, `kb_standards`, `industry_docs`, `default`, `general`

---

## 二、空心 / 冗余 Bank 详细分析

### 🔴 A 组 — 立即删除（0 facts，无文档引用，无配置引用）

| bank | 原因 | 说明 |
|------|------|------|
| `kb_standards` | 空心重复 | `kb_standard`（10,346 facts）的重复创建，0 facts |
| `industry_docs` | 空心重复 | `kb_industry`（1,812 facts）的重复创建，0 facts |
| `default` | 空心孤儿 | Hindsight 自动创建的默认 bank，未被 kb2-web 任何组件引用 |

### 🔴 B 组 — 建议迁移/清理（有少量 facts 但被替代）

| bank | fact_count | 问题 | 处理建议 |
|------|-----------|------|---------|
| `kb` | 2,838 | 旧聚合库。`recall()` 中 `bank="kb"` 等同于 `bank="all"`(查所有 active banks)。文档 `_verify_searchable` 硬编码 `v_bank="kb"` | ⚠️ 迁移到 `kb_general` 后再删除 |
| `general` | 50 | Hindsight 自创建的老 bank，被 `kb_general`（6,710 facts）替代，无文档引用 | 确认无引用后可直接删除 |
| _(missing)_ `kb_template` | N/A | 配置中引用但 Hindsight 中没有该 bank | 需创建空 bank 或移除配置引用 |

### ✅ C 组 — 保留（活跃使用中）

`kb_general`, `kb_standard`, `kb_industry`, `kb_project`, `kb_tech`, `kb_checklist`, `kb_xhs`

---

## 三、代码依赖分析

### 3.1 `bank="kb"` 遗留引用

**文件：** `backend/app/services/retrieval.py:260`
```python
async def recall(query, limit=5, bank="kb", ...):
    # bank="kb" → 查询所有 active hindsight banks
```

`bank="kb"` 被用作默认参数，但实际行为等同于 `bank="all"`（走第 280 行的聚合查询分支）。删除 `kb` Hindsight bank 后不会影响 recall 功能，但需要更新：

- `retrieval.py:260` — 默认参数从 `"kb"` 改为 `"all"`
- `retrieval.py:280` — 条件 `bank in ("all", "kb")` 改为 `bank in ("all",)`

**文件：** `backend/app/api/documents.py:71`
```python
async def _verify_searchable(v_doc_id, v_title, v_original_len, v_bank="kb"):
```
上传后的可搜索验证使用 `v_bank="kb"` 作为默认 bank。需要改为 `v_bank="kb_general"`。

**文件：** `backend/app/api/documents.py:459` 中的 rag-eval recall：
```python
recalled = await recall(tc["q"], limit=10, bank="kb")
```
需要改为 `bank="all"`。

### 3.2 `general` bank 被 `kb_general` 取代

- 前端 `business` 和 `methodology` 均使用 `kb_general`（共享）
- DB 中无文档使用 `general` 作为 hs_bank
- 删除安全

### 3.3 `kb_template` 缺失

**文件：** `backend/app/services/retrieval.py:38`
```python
"templates": {"name": "方案模板", "hindsight": "kb_template", ...}
```
配置存在，Hindsight 中无此 bank。上传文档时若选择「方案模板」bank，上传到空的 `kb_template` 会因 Hindsight 404 失败。需要创建该 bank 或暂时注释该配置。

---

## 四、清理方案

### 方案 A — 立即删除 3 个空心 bank（无风险）

```
DELETE /v1/default/banks/kb_standards    # 已测试：成功返回 {"success":true}
DELETE /v1/default/banks/industry_docs
DELETE /v1/default/banks/default
```

**验证方法：**
```bash
curl http://localhost:8888/v1/default/banks
# 确认返回中不再包含上述 3 个 bank
```

### 方案 B1 — 迁移 `kb` 数据并删除（中风险，需分步执行）

`kb` 有 2,838 facts，需要先确认这些 facts 是否已经被其他 bank 覆盖。

**步骤：**
1. 从 `kb` 中抽样 recall 验证是否已被 `kb_general`/`kb_standard`/`kb_industry` 覆盖
2. 更新代码中的 `"kb"` 引用为 `"all"`（见第五节）
3. 执行 DELETE

**验证方法：**
```bash
# 验证 kb 中的内容在其他 bank 中可召回
curl -X POST http://localhost:8888/v1/default/banks/kb/memories/recall \
  -H 'Content-Type: application/json' \
  -d '{"query":"政务信息化项目","limit":5}'

curl -X POST http://localhost:8888/v1/default/banks/kb_general/memories/recall \
  -H 'Content-Type: application/json' \
  -d '{"query":"政务信息化项目","limit":5}'
# 比较结果，如果 kb_general 结果覆盖 kb 则 kb 可安全删除
```

### 方案 B2 — 删除 `general` bank（低风险）

- fact_count=50，最后写入 2026-06-02，无文档引用
- 直接 DELETE

**验证方法：**
```bash
curl http://localhost:8888/v1/default/banks
# 确认不含 general
```

### 方案 C — 创建 `kb_template`（可选）

若需要修复「方案模板」bank，执行：
```
POST /v1/default/banks  {"bank_id": "kb_template", "name": "kb_template"}
```

### 方案 D — `business` / `methodology` bank 独立化（远期优化）

当前 `business`(商业分析) 和 `methodology`(方法论) 共享 `kb_general` bank，导致「商业分析」问答时也召回到「综合文件」的内容。远期可考虑：
1. 在 Hindsight 中创建 `kb_business` 和 `kb_methodology`
2. 迁移对应文档
3. 更新 `_HARDCODED_BANKS`

**本次不执行，列为远期建议。**

---

## 五、代码修改清单

### 5.1 `retrieval.py` — 更新 `bank="kb"` 默认参数

| 位置 | 当前代码 | 修改后 |
|------|---------|--------|
| L260 | `async def recall(..., bank: str = "kb", ...)` | `async def recall(..., bank: str = "all", ...)` |
| L280 | `if bank in ("all", "kb") or not hs_bank:` | `if bank == "all" or not hs_bank:` |

### 5.2 `documents.py` — 更新 `_verify_searchable` bank 默认值

| 位置 | 当前代码 | 修改后 |
|------|---------|--------|
| L71 | `v_bank="kb"` | `v_bank="all"` |
| L459 | `bank="kb"` | `bank="all"` |

### 5.3 `documents.py` — 更新 rag-eval recall bank（可选）

| 位置 | 当前代码 | 修改后 |
|------|---------|--------|
| L459 | `bank="kb"` | `bank="all"` |

---

## 六、验证方法

### 6.1 删除前验证

```bash
# 1. 确认空心 bank 列表
curl http://localhost:8888/v1/default/banks | python3 -m json.tool

# 2. 验证 kb 是否与 kb_general 内容重叠
curl -X POST http://localhost:8888/v1/default/banks/kb/memories/recall \
  -H 'Content-Type: application/json' -d '{"query":"测试","limit":3}'
curl -X POST http://localhost:8888/v1/default/banks/kb_general/memories/recall \
  -H 'Content-Type: application/json' -d '{"query":"测试","limit":3}'
```

### 6.2 删除后验证

```bash
# 1. 确认 bank 列表已清理
curl http://localhost:8888/v1/default/banks

# 2. 确认 recall 仍然正常工作（使用 all 或具体 bank）
curl -X POST http://localhost:8888/v1/default/banks/kb_general/memories/recall \
  -H 'Content-Type: application/json' -d '{"query":"政务信息化","limit":5}'

# 3. 重启 kb2-web 后端，确认接口正常
# 4. 跑一条完整问答验证流程
```

### 6.3 代码修改后验证

```bash
# 1. 运行单元测试
cd /home/ubuntu/kb2-web
python -m pytest backend/tests/ -x -v --timeout=60 2>&1 | tail -50

# 2. 启动后端并测试 API
curl http://localhost:3002/api/banks
curl http://localhost:3002/api/query -X POST -H 'Content-Type: application/json' \
  -d '{"query":"等保2.0 安全要求","bank":"standards"}'
```

---

## 七、执行计划汇总

| 优先级 | Bank | 操作 | 风险 | 前置条件 |
|--------|------|------|------|---------|
| P0 | `kb_standards` | DELETE | 无 | 无 |
| P0 | `industry_docs` | DELETE | 无 | 无 |
| P0 | `default` | DELETE | 无 | 无 |
| P1 | `general` | DELETE | 低 | 无文档引用（已验证） |
| P1 | `kb` | 代码修改 → 迁移确认 → DELETE | 中 | 需更新代码中的 `"kb"` 引用为 `"all"` |
| P2 | `kb_template` | 创建 bank 或注释配置 | 低 | 确认是否需要修复 |
| 远期 | `business`/`methodology` | 独立 bank | 低 | 未来再做 |

---

## 附录 A：依赖文件清单

| 文件路径 | 涉及内容 |
|---------|---------|
| `backend/app/services/retrieval.py` | `_HARDCODED_BANKS`, `recall()` bank 默认值 |
| `backend/app/api/documents.py` | `_verify_searchable()`, `get_document_content()`, rag-eval |
| `backend/app/api/upload.py` | `hs_bank` 路由（读取配置） |
| `backend/app/api/banks.py` | bank CRUD（删除 API） |
| `backend/app/services/concept_gen.py` | `_BANK_TO_DOMAIN` 映射 |
| `backend/app/repositories/document_repo.py` | `save()` 的 `hs_bank` 参数 |
| `backend/app/repositories/vector_repo.py` | `HindsightStore` 写入 |
| `backend/tests/integration/test_api_endpoints.py` | 集成测试 mock |
| `scripts/reindex_hindsight.py` | 重索引脚本 |
| `backend/scripts/backfill_*.py` | 数据回填脚本（含 `bank="kb"` 引用） |

## 附录 B：Hindsight API 参考

```bash
# 列出所有 bank
GET /v1/default/banks

# 删除 bank（含所有 memories）
DELETE /v1/default/banks/{bank_id}

# 创建 bank
POST /v1/default/banks  {"bank_id": "xxx", "name": "xxx"}

# 验证 recall
POST /v1/default/banks/{bank_id}/memories/recall  {"query":"...", "limit":5}
```
