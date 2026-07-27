"""Seed script — decompose kb2-v2-pipeline-deep-analysis.md into wiki entries."""
import json
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("APP_ENV", "production")

from app.services import wiki_service
from app.models.database import init_db

init_db()

entries = [
    # ════════════════════════════════════════════════════════════
    # 条目1: 管线架构总览
    # ════════════════════════════════════════════════════════════
    {
        "title": "kb2-web 管线架构总览",
        "standard_no": "",
        "category": "guide", "subcategory": "架构文档",
        "tags": ["架构", "管线", "pipeline", "kb2-web"],
        "summary": "kb2-web 知识库 v2 完整管线涵盖上传→解析→切片→清洗→入库→检索→召回增强→门控→生成的9个环节，自研FastAPI无需RAG框架。",
        "content": json.dumps({
            "scope": "概览整个知识库v2的技术架构和管线流程，适合新开发者快速了解系统全貌。",
            "key_clauses": (
                "全链路：上传→MinerU解析（4种回退）→G1/G2/G3质量门禁→标题感知切片→清洗（8阶段）→三层存储（SQLite+pgvector+Hindsight）→三路召回（BM25+语义+Hindsight）→RRF融合→Rerank（4模式）→标准号Boost→D2-B费用管道→Wiki注入→速查卡注入→四级置信度门控（L1/L1.5/L2/L3）→B03库外检测→DeepSeek生成\n"
                "核心文件数：60+ Python 文件（api/services/models/utils/repositories）\n"
                "后端行数：17,265 行 Python（FastAPI + SQLAlchemy）\n"
                "前端行数：5,780 行 Vue3（18 组件/页面视图）\n"
                "对比主流方案（LangChain/LlamaIndex）：自研零框架锁定 vs 生态依赖"
            ),
            "application": "架构评审、新人入职、系统文档参考。",
        }, ensure_ascii=False),
        "importance": 9, "status": "published",
    },
    # ════════════════════════════════════════════════════════════
    # 条目2: 切片策略详解
    # ════════════════════════════════════════════════════════════
    {
        "title": "kb2-web 自适应父子分块策略",
        "standard_no": "",
        "category": "guide", "subcategory": "切片",
        "tags": ["chunking", "切片", "父子分块", "标题感知"],
        "summary": "kb2-web 实现标题感知的自适应父子分块策略，取代固定窗口分块。核心参数：parent_size=6000, child_size=500, overlap=75。支持GB标准、法规、通用、Excel四类文档的分块策略。",
        "content": json.dumps({
            "scope": "切片服务 chunking.py（1019行），覆盖所有文档类型的分块策略。",
            "key_clauses": (
                "核心参数：parent_size=6000字符, child_size=500字符, overlap=75字符, min_child_size=200字符\n"
                "GB标准：叶子标题层级（X.X.X）下内容为child，祖先标题下组合为parent\n"
                "法规：每条（第N条）为独立child，3-5条为一组parent\n"
                "通用：parent_child_chunk()滑动窗口\n"
                "Excel表格：每行为child，表格整体为parent\n"
                "关键机制：①标题感知分块_heading_chunk_gb()从headings列表遍历 ②短段落合并缓冲区（<200字符暂存合并）③句边界感知截断（回退到最近句号/问号/换行符）④section_hint链增强（分层标题链如'3 术语和定义/3.1 信息系统'）"
            ),
            "application": "切片参数调优、新增文档类型分块策略、chunk召回质量分析。",
        }, ensure_ascii=False),
        "importance": 8, "status": "published",
    },
    # ════════════════════════════════════════════════════════════
    # 条目3: 三路召回+RRF+Rerank
    # ════════════════════════════════════════════════════════════
    {
        "title": "kb2-web 三路召回+RRF融合+Rerank机制",
        "standard_no": "",
        "category": "guide", "subcategory": "检索",
        "tags": ["召回", "RRF", "rerank", "检索", "BM25"],
        "summary": "kb2-web 实现 BM25全文搜索 + pgvector语义搜索 + Hindsight向量搜索的三路并行召回，经 Reciprocal Rank Fusion（k=60）等权融合后，再经4种Rerank模式之一排序。",
        "content": json.dumps({
            "scope": "检索服务 retrieval.py（1274行），涵盖三路召回、RRF融合、Rerank、标准号Boost、同义词扩展。",
            "key_clauses": (
                "三路召回：\n"
                "  BM25全文搜索：SQLite FTS5-like + rank_bm25库BM25Okapi，精确关键词匹配\n"
                "  pgvector语义搜索：异步 async pgvector search()，多bank并行\n"
                "  Hindsight向量搜索：第二pgvector连接独立搜索，覆盖尾部命中\n"
                "RRF融合：score(d) = Σ(1/(k+rank_i(d)))，k=60\n"
                "4种Rerank模式：\n"
                "  cross_encoder：交叉编码器API重排\n"
                "  multidim：keyword=0.43, dense=0.43, confidence=0.025, freshness=0.015, source_count=0.01, chunk_position=0.10\n"
                "  confidence：文档置信度分排序\n"
                "  freshness：半衰期365天时效性优先\n"
                "标准号Boost（standard_boost.py 267行）：正则提取标准号→title LIKE精确匹配→直接注入doc_facts top-5\n"
                "同义词扩展：费用查询扩展（监理费→监理费用/监理收费），多路OR查询"
            ),
            "application": "检索质量调优、Rerank权重调整、新bank配置、召回策略评估。",
        }, ensure_ascii=False),
        "importance": 9, "status": "published",
    },
    # ════════════════════════════════════════════════════════════
    # 条目4: 四级置信度门控+B03
    # ════════════════════════════════════════════════════════════
    {
        "title": "kb2-web 四级置信度门控与B03库外检测",
        "standard_no": "",
        "category": "guide", "subcategory": "质量门禁",
        "tags": ["置信度", "门控", "quality_gates", "B03", "拒答"],
        "summary": "kb2-web 实现L1/L1.5/L2/L3四级置信度门控系统，结合B03库外主题检测，显著降低幻觉率和拒答误判。",
        "content": json.dumps({
            "scope": "质量门禁 quality_gates.py（395行）+ confidence.py（305行），覆盖检索前到生成后全链路质量检查。",
            "key_clauses": (
                "四级门控：\n"
                "  L1：source_count<=0（检索为空）→直接拒答\n"
                "  L1.5：纯引用模式无实质条款→拒答（费用类跳过）\n"
                "  L2：coverage<0.5且无精确匹配+无标准号boost→拒答\n"
                "  L3（后生成）：校验score<25%→替代回答\n"
                "Coverage计算：coverage = len(matched_docs) / min(10, len(all_relevant_docs))\n"
                "特殊规则：category参数跳过L2、费用类跳过L1.5、标准号boost放行L2\n"
                "Doc Facts重排（H阶段）：按chunk命中率排序，每doc最多截取前3个最高分chunk\n"
                "B03库外检测：内置8领域56关键词，查询主题不属于KB领域时拒答"
            ),
            "application": "拒答策略调优、L2/L3阈值调整、新领域添加关键词、质量评估。",
        }, ensure_ascii=False),
        "importance": 8, "status": "published",
    },
    # ════════════════════════════════════════════════════════════
    # 条目5: D2-B费用管道
    # ════════════════════════════════════════════════════════════
    {
        "title": "kb2-web D2-B费用类专用管道",
        "standard_no": "",
        "category": "guide", "subcategory": "费用查询",
        "tags": ["D2-B", "费用", "费率表", "公平分发", "互斥"],
        "summary": "D2-B是kb2-web针对政务信息化费用查询的专用管道，实现标题精确匹配→32个费用关键词打分→两阶段公平分发→费用类型互斥→Hindsight recall补充的完整流程。",
        "content": json.dumps({
            "scope": "费用专用管道 fee_utils.py（372行），解决普通RAG难以命中政务取费表的问题。",
            "key_clauses": (
                "完整流程：用户查询（含费用关键词）→title LIKE %费用%精确匹配→关键词打分（28个费用关键词：费率/计费额/收费基价等）→两阶段公平分发→费用类型互斥→Hindsight recall补充\n"
                "公平分发两阶段：\n"
                "  第一阶段：每个匹配文档至少分到1个chunk\n"
                "  第二阶段：剩余budget按chunk relevance评分梯度分配 _distribute_by_relevance()\n"
                "费用类型互斥：等保≠验收测评，互斥类型不混合，避免LLM混淆费率表\n"
                "Mismatch排除：调整系数/编制说明/前言等元数据片段自动过滤\n"
                "per-doc公平分配：每个doc至少保留1个top chunk，余量按score分配"
            ),
            "application": "费用查询质量调优、关键词更新、评分参数调整、政务信息化特有场景。",
        }, ensure_ascii=False),
        "importance": 9, "status": "published",
    },
    # ════════════════════════════════════════════════════════════
    # 条目6: 存储架构+Wiki层+缓存
    # ════════════════════════════════════════════════════════════
    {
        "title": "kb2-web 三层存储架构与缓存策略",
        "standard_no": "",
        "category": "guide", "subcategory": "存储",
        "tags": ["存储", "SQLite", "pgvector", "Hindsight", "缓存", "Wiki"],
        "summary": "kb2-web 采用 SQLite（元数据+BM25）+ pgvector（向量主库）+ Hindsight（辅助向量）的三层存储，配合L1精确+L2语义+BM25索引三层缓存，以及SQLite Wiki结构化知识层。",
        "content": json.dumps({
            "scope": "存储架构涉及 data_cleaning.py（311行清洗）、三层写入逻辑、cache_service.py（223行）、Wiki_entry结构化知识。",
            "key_clauses": (
                "三层存储：\n"
                "  元数据层（SQLite）：documents表（12字段：title, bank, searchable, published_date等）+ parent_chunks表（父块文字，BM25搜索用）\n"
                "  向量主库（pgvector）：vector_chunks表（embedding+完整chunk文本+JSONB metadata）\n"
                "  辅助向量（Hindsight）：第二pgvector连接，用于多路召回尾部互补\n"
                "Wiki结构化层（SQLite）：wiki_entries+wiki_relations，45条/13分类（standard/faq/guide/term）\n"
                "三层缓存：\n"
                "  L1精确匹配：SQLite query_cache, SHA256(q+bank), TTL=86400s\n"
                "  L2语义缓存：SQLite+BM25, hash(q+bank+mode+category), TTL=600s\n"
                "  BM25索引：每bank独立，TTL=600s增量检测，上传后立即invalidate_bm25_cache()\n"
                "速查卡注入（concept_summary.py）：文档级概念摘要50-100字，按置信度评分排序"
            ),
            "application": "存储调优、缓存策略评估、Wiki内容维护、新存储层扩展。",
        }, ensure_ascii=False),
        "importance": 8, "status": "published",
    },
]

print(f"Inserting {len(entries)} pipeline wiki entries...")
count = 0
skip_count = 0
for e in entries:
    # Check if entry already exists (by title)
    existing = wiki_service.search_entries(query=e["title"][:20])
    if existing and any(ex["title"] == e["title"] for ex in existing):
        print(f"  ⏭ SKIP (exists): {e['title']}")
        skip_count += 1
        continue
    eid = wiki_service.create_entry(**e)
    if eid:
        count += 1
        print(f"  [{eid}] {e['title']}")
    else:
        print(f"  ❌ FAILED: {e['title']}")

print(f"\nDone: {count} created, {skip_count} skipped.")
