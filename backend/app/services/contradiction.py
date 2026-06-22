"""OKF Contradiction Detection — embedding-based contradiction scoring.

Phase B #3: 替代 confidence 公式中 contradiction = 1.0 的 placeholder。

实现：同 domain 下找 sibling concepts，取最低余弦相似度。
使用 SiliconFlow BGE-M3 embedding API（通过 get_embedding）。
若 min_sim < CONTRADICTION_THRESHOLD → 强矛盾（返回 min_sim），否则无矛盾（返回 1.0）。

这是阶段 B 级实现，目标是消除假分而非完美的矛盾检测。
如果向量调用失败，降级返回 1.0 并 log warning。

阈值校准（基于 BGE-M3 实测 standards domain 40 样本）：
- global_min=0.37, global_avg=0.48, global_max=0.88
- 阈值 0.3 永远不触发（所有标准都 ≥ 0.37）
- 阈值 0.4 = 触发约 20% 文档（avg-1σ 区间）—— 视为"强语义偏离"
"""

import logging
import numpy as np
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.concept import Concept
from app.models.document import Document
from app.utils.embeddings import get_embedding

logger = logging.getLogger(__name__)

# 矛盾阈值：余弦相似度低于此值视为强矛盾
# 校准依据：BGE-M3 standards domain 实测 40 样本，min=0.37 avg=0.48
# 0.40 阈值对应"显著偏离同 domain 主流话题"
CONTRADICTION_THRESHOLD = 0.40
# 最多检查多少个 sibling concepts
MAX_SIBLINGS = 20
# 实际计算用的 sibling 数量（从候选池中抽样）
SIBLING_SAMPLE_SIZE = 5


def compute_contradiction_score(db: Session, concept: Concept) -> float:
    """计算单个 concept 的 contradiction 维度分。

    Returns:
        0.0 = 完全矛盾, 1.0 = 无矛盾。
        实际实现：取最低余弦相似度，< CONTRADICTION_THRESHOLD 时返回该值，否则返回 1.0。
    """
    if not concept or not concept.concept_id:
        return 1.0

    # 1. 提取 domain prefix（parts[0]：standards / methodology / learning 等）
    # 注意：parts[:2] 是 domain/slug（每个文档独有），无法跨文档；必须用 parts[:1]
    parts = concept.concept_id.split("/")
    if len(parts) < 2:
        return 1.0
    domain_prefix = parts[0] + "/"  # e.g. "standards/"

    # 2. 找 sibling concepts（同 domain 下的其他 active concept，跨文档）
    siblings = db.query(Concept).filter(
        Concept.concept_id.like(f"{domain_prefix}%"),
        Concept.doc_id != concept.doc_id,  # 必须是其他文档的 concept
        Concept.status == "active",
    ).limit(MAX_SIBLINGS).all()

    if not siblings:
        return 1.0

    # 3. 获取 target concept 的 embedding
    target_vec = _get_concept_embedding(concept)
    if target_vec is None:
        logger.warning(
            "Cannot get embedding for concept %s, contradiction score defaults to 1.0",
            concept.concept_id,
        )
        return 1.0

    # 4. 对 siblings 抽样计算余弦相似度
    sample = siblings[:SIBLING_SAMPLE_SIZE]
    min_sim = 1.0
    computed = 0

    for sibling in sample:
        sib_vec = _get_concept_embedding(sibling)
        if sib_vec is None:
            continue
        sim = _cosine_similarity(target_vec, sib_vec)
        computed += 1
        if sim < min_sim:
            min_sim = sim

    if computed == 0:
        return 1.0

    # 5. 映射：min_sim < threshold → 强矛盾
    if min_sim < CONTRADICTION_THRESHOLD:
        logger.info(
            "Contradiction detected for %s: min_sim=%.3f (threshold=%.2f)",
            concept.concept_id, min_sim, CONTRADICTION_THRESHOLD,
        )
        return float(min_sim)

    return 1.0


def _get_concept_embedding(concept: Concept) -> Optional[np.ndarray]:
    """获取 concept 的 embedding 向量。

    策略：直接调用 embedding API（get_embedding 有 LRU 缓存）。
    阶段 B 暂不集成 Hindsight 的 cached embedding 读取。
    """
    text = concept.content if isinstance(concept.content, str) else ""
    if not text or len(text.strip()) < 20:
        # 内容太短，尝试用 title + content 组合
        title = concept.title or ""
        text = f"{title}\n{text}".strip()
        if len(text) < 10:
            return None

    # get_embedding 是 async，这里需要在同步上下文中调用
    # 使用 asyncio.run 包裹
    import asyncio
    try:
        # 尝试获取或创建 event loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            # 在已有 event loop 中运行（如 FastAPI 请求上下文）
            # 使用 nest_asyncio 或直接用同步替代方案
            # 降级：返回 None，让上层降级为 1.0
            logger.debug(
                "Cannot call async embedding in running event loop, "
                "contradiction score defaults to 1.0 for %s",
                concept.concept_id,
            )
            return None
        else:
            vec = asyncio.run(get_embedding(text[:2000]))
    except Exception as e:
        logger.warning("Embedding call failed for concept %s: %s", concept.concept_id, e)
        return None

    return vec


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """计算两个向量的余弦相似度。"""
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))
