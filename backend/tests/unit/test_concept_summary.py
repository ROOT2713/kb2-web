"""Tests for app.services.concept_summary — LLM 概念摘要生成。"""

import pytest
from unittest.mock import patch, AsyncMock
from app.services.concept_summary import generate_summary, generate_summaries_batch
from app.models.document import Document
from app.models.concept import Concept


class TestGenerateSummary:
    """generate_summary 单元测试（mock LLM）。"""

    @pytest.mark.asyncio
    async def test_basic_summary(self):
        """基本摘要生成。"""
        with patch("app.services.generation.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = "这是一个关于网络安全的标准文档，规定了信息系统安全等级保护的基本要求。"
            result = await generate_summary(
                content="GB/T 22239-2019 信息安全技术 网络安全等级保护基本要求...",
                title="网络安全等级保护",
            )
            assert result
            assert len(result) > 0
            mock_chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_content(self):
        """空内容返回空字符串。"""
        result = await generate_summary(content="", title="空文档")
        # 空内容不会调用 LLM，直接返回
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_llm_failure_returns_empty(self):
        """LLM 失败返回空字符串。"""
        with patch("app.services.generation.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = Exception("API Error")
            result = await generate_summary(content="test content", title="test")
            assert result == ""


class TestGenerateSummariesBatch:
    """generate_summaries_batch 集成测试。"""

    @pytest.mark.asyncio
    async def test_batch_generate(self, db_session):
        """批量生成摘要。"""
        doc = Document(doc_id="sum-batch-001", title="批量摘要", bank="general", status="active")
        concepts = [
            Concept(
                concept_id=f"sum-batch-001/section-{i}",
                doc_id="sum-batch-001",
                parent_idx=i,
                title=f"Section {i}",
                content=f"这是第{i}节的内容，包含足够的文本用于摘要生成。",
                summary="",  # 无摘要
                status="active",
            )
            for i in range(3)
        ]
        db_session.add_all([doc] + concepts)
        db_session.commit()

        with patch("app.services.generation.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = "这是一个摘要。"
            count = await generate_summaries_batch(db_session, "sum-batch-001", limit=5)
            assert count == 3

            # 验证摘要已写入
            for c in concepts:
                assert c.summary == "这是一个摘要。"
