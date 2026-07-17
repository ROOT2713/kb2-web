# 手术脚本：kb2-web P0 拒答修复
## 三处修改，全部确定

### 修改 1: Generation Prompt — 增加库外检测约束（query_engine.py L1685-L1690 之间插入）
用户查询完全无关时，LLM 必须优先拒答而非编造。

**插入位置**: 在 L1685 `prompt = f"""【安全约束】` 之后、L1690 回答原则之前
**插入内容**:
```
8. 【文档-问题相关性约束】（最高优先级，覆盖以下所有回答原则）：
   a. 从【文档内容】中提取的 chunk 必须与用户问题主题实质相关才能使用
   b. 如何判断不相关：
      - 用户问文学/医学/菜谱/体育/娱乐等话题，但 chunks 全部来自技术标准/造价规范
      - chunks 中仅出现零星的通用词汇匹配（"什么"、"标准"等），但无任何实质内容对应用户问题的主题
      - top-3 chunks 的主题（建筑/供配电/声学/WiFi）与用户问题（文学/烹饪/体育）明显不在同一领域
   c. 如果判断为不相关：必须直接输出以下固定拒答语并拒绝扩展：
      "知识库中未找到与您问题直接相关的信息。请尝试换一种方式提问，或确认您的查询范围。"
   d. 本规则优先级高于【输出要求】中的最低字数要求——相关性不足时不允许编造字数
```

### 修改 2: L2 置信度增强 — 语义相关度门控（query_engine.py ~L2005）
在现有 L2 拒答逻辑基础上，增加"top chunk 语义相关度"检查。

**修改位置**: query_engine.py L1993-L2019（现有 B02 + L2 主门控）
**修改内容**:
当前 B02：
```python
    if source_count >= 3 and coverage < 0.3 and not has_exact_match:
        return reject
```
改为（B02 增强 + 新增 B03 语义门控）：
```python
    # ── B02: 关键词密度拒答 ──
    # 场景：source_count≥3 但 coverage<0.3且无精确匹配 → 只有引用无实质
    if source_count >= 3 and coverage < 0.3 and not has_exact_match:
        logger.info(
            "[CONFIDENCE] Level 2 keyword density reject: source_count=%d, coverage=%.2f, kw=%d",
            source_count, coverage, len(query_keywords),
        )
        return {"reject_type": "low_coverage", "message": _REJECT_MSG_LOW_COVERAGE}

    # ── B03: top-3 chunk 语义相关性拒答 ──
    # 场景：source_count≥2 且 coverage≥0.5 但 top chunks 与查询主题完全不相关
    # 使用 jieba 主题分类做轻量检测
    if source_count >= 2 and not has_exact_match:
        try:
            import jieba
            _q_words = set(w for w in jieba.cut(q) if len(w) >= 2)
            # 政务KB的主题域关键词
            _kb_domains = {
                "信息化": ["信息化", "测评", "软件", "功能点", "造价", "取费", "验收", "评测"],
                "标准": ["标准", "规范", "规定", "要求", "条款", "GB", "GB/T"],
                "安全": ["等保", "等级保护", "安全", "防火墙", "入侵", "漏洞", "密码"],
                "机房": ["数据中心", "机房", "供配电", "UPS", "温湿度"],
                "声学": ["声学", "噪声", "混响", "隔声", "厅堂", "剧场"],
                "网络": ["WiFi", "信道", "AP", "无线", "802.11"],
                "建筑": ["弱电", "消防", "安防", "综合布线"],
            }
            # 提取查询的主题关键词
            _q_domain_keywords = set()
            for k in _q_words:
                for domain, kws in _kb_domains.items():
                    if any(dk in k for dk in kws):
                        _q_domain_keywords.add(k)

            if len(_q_domain_keywords) == 0 and len(_q_words) >= 2:
                # 查询中无任何政务KB领域关键词 → 极可能库外
                # 再检查 top chunks 是否包含政务领域内容
                top_chunks_text = " ".join(list(ctx.get("_all_chunk_texts", []))[:3]).lower()
                _domain_hit = any(dk in top_chunks_text for domain_kws in _kb_domains.values() for dk in domain_kws)
                if _domain_hit:
                    # chunks 是政务内容但与查询无关 → 库外
                    logger.info(
                        "[CONFIDENCE] Level 2 B03 topic mismatch reject: q_domain_keywords=0, source_count=%d, q=%s",
                        source_count, q[:40],
                    )
                    return {"reject_type": "topic_mismatch", "message": _REJECT_MSG_LOW_COVERAGE}
        except ImportError:
            pass  # jieba not available, skip B03
```

### 修改 3: L2 函数签名增加 ctx 参数（query_engine.py L1831）
当前 `_assess_recall_confidence` 函数签名没有 ctx 中的 chunk 文本，需要从已有的 all_results 传递。

**修改位置**: query_engine.py L355 （query.py 中调用 _assess_recall_confidence 处）
**不需要改签名** —— 因为 L2 已经用了 `ctx["doc_facts"]`，B03 也需要 doc_facts 中的 chunk 文本。

**实际需要**: 在 `_assess_recall_confidence` 中构建 chunk 文本列表（B03 用）
在 L1870-L1876 已有 `_all_chunk_texts` 构建代码。B03 可以直接复用该变量。

B03 需要放在 L2005 位置——此时 `_all_chunk_texts` 变量在 L1.5 块中已经出了作用域。需要重新构建。

所以做法：在 B02 之后、B03 之前重新构建一次 top chunks 文本，或者把 L1.5 的 _all_chunk_texts 提升为函数级变量。

**更简单方案**：把 B03 放在 L1.5 块内（L1894 之后），或者直接提取 ctx["doc_facts"]。

让我简化：B03 从 doc_facts 直接构建，不依赖 _all_chunk_texts。

### 修改汇总

| # | 文件 | 位置 | 改动 | 行数 |
|---|------|------|------|:----:|
| 1 | query_engine.py | L1685-L1690 之间 | 插入【文档-问题相关性约束】规则 8 | +12行 |
| 2 | query_engine.py | L1995-L2003（B02 区块后） | 插入 B03 语义相关性门控 | +45行 |
| 3 | query.py | L355-L358 (confidence gate 调用处) | 不需要修改，_assess_recall_confidence 已接收 ctx |
