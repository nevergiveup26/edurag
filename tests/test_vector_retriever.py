"""retriever.vector_retriever 向量检索器测试"""
import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from core.models import DocumentChunk


_EMBED_SENTINEL = object()


def make_chunk(chunk_id, content="test", doc_id="d1", embedding=_EMBED_SENTINEL):
    if embedding is _EMBED_SENTINEL:
        embedding = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    return DocumentChunk(
        chunk_id=chunk_id, doc_id=doc_id, content=content,
        metadata={}, embedding=embedding,
    )


class TestVectorRetrieverInit:
    def test_default_init(self):
        from retriever.vector_retriever import VectorRetriever
        retriever = VectorRetriever()
        assert retriever._chunks == []


class TestBuildIndex:
    def test_build_index_stores_chunks(self):
        from retriever.vector_retriever import VectorRetriever
        retriever = VectorRetriever()
        chunks = [make_chunk("c1"), make_chunk("c2"), make_chunk("c3")]
        retriever.build_index(chunks)
        assert len(retriever._chunks) == 3

    def test_build_index_empty(self):
        from retriever.vector_retriever import VectorRetriever
        retriever = VectorRetriever()
        retriever.build_index([])
        assert retriever._chunks == []

    def test_build_index_some_without_embedding(self):
        from retriever.vector_retriever import VectorRetriever
        retriever = VectorRetriever()
        chunks = [
            make_chunk("c1", embedding=np.array([0.1, 0.2])),
            make_chunk("c2", embedding=None),
            make_chunk("c3", embedding=np.array([0.3, 0.4])),
        ]
        retriever.build_index(chunks)
        assert len(retriever._chunks) == 3


class TestSearch:
    def test_empty_index(self):
        from retriever.vector_retriever import VectorRetriever
        retriever = VectorRetriever()
        assert retriever.search("query") == []

    def test_embed_query_failure(self):
        from retriever.vector_retriever import VectorRetriever
        retriever = VectorRetriever()
        retriever._chunks = [make_chunk("c1")]
        retriever.vectorizer.embed_query = MagicMock(side_effect=Exception("embed failed"))
        assert retriever.search("query") == []

    def test_search_returns_results(self):
        from retriever.vector_retriever import VectorRetriever
        retriever = VectorRetriever()
        chunks = [make_chunk("c1"), make_chunk("c2"), make_chunk("c3")]
        retriever.build_index(chunks)

        retriever.vectorizer.embed_query = MagicMock(return_value=np.array([0.1, 0.2, 0.3]))
        retriever.vectorizer.cosine_similarity = MagicMock(return_value=0.85)

        results = retriever.search("query", top_k=2)
        assert len(results) == 2
        assert results[0].source == "vector"
        assert results[0].score == 0.85

    def test_search_respects_top_k(self):
        from retriever.vector_retriever import VectorRetriever
        retriever = VectorRetriever()
        retriever._chunks = [make_chunk(f"c{i}") for i in range(10)]
        retriever.vectorizer.embed_query = MagicMock(return_value=np.array([0.1, 0.2, 0.3]))
        retriever.vectorizer.cosine_similarity = MagicMock(return_value=0.7)

        results = retriever.search("query", top_k=3)
        assert len(results) == 3

    def test_search_skip_none_embedding(self):
        from retriever.vector_retriever import VectorRetriever
        retriever = VectorRetriever()
        chunks = [
            make_chunk("c1", embedding=None),
            make_chunk("c2"),
        ]
        retriever.build_index(chunks)
        retriever.vectorizer.embed_query = MagicMock(return_value=np.array([0.1, 0.2, 0.3]))
        retriever.vectorizer.cosine_similarity = MagicMock(return_value=0.9)

        results = retriever.search("query", top_k=5)
        assert len(results) == 1  # 只有 c2 有 embedding

    def test_search_similarity_threshold(self):
        from retriever.vector_retriever import VectorRetriever
        retriever = VectorRetriever()

        # 不同分数
        scores = [0.9, 0.05, 0.8]
        call_count = [0]

        def side_effect(q_emb, c_emb):
            s = scores[call_count[0] % len(scores)]
            call_count[0] += 1
            return s

        retriever._chunks = [make_chunk(f"c{i}") for i in range(3)]
        retriever.vectorizer.embed_query = MagicMock(return_value=np.array([0.1]))
        retriever.vectorizer.cosine_similarity = MagicMock(side_effect=side_effect)

        results = retriever.search("query", top_k=5, similarity_threshold=0.1)
        assert len(results) == 2  # 0.9 和 0.8 通过, 0.05 被过滤

    def test_search_dimension_mismatch_skipped(self):
        from retriever.vector_retriever import VectorRetriever
        retriever = VectorRetriever()
        retriever._chunks = [make_chunk("c1"), make_chunk("c2")]
        retriever.vectorizer.embed_query = MagicMock(return_value=np.array([0.1, 0.2, 0.3]))
        # 第一次抛 ValueError，第二次正常
        retriever.vectorizer.cosine_similarity = MagicMock(side_effect=[
            ValueError("dimension mismatch"),
            0.75,
        ])

        results = retriever.search("query", top_k=5)
        assert len(results) == 1  # c1 被跳过，c2 正常

    def test_search_with_metadata_filter(self):
        import sys
        from retriever.vector_retriever import VectorRetriever

        # MetadataExtractor 是 search() 内部的 local import
        mock_extractor = MagicMock()
        mock_extractor.matches_filter = lambda meta, filt: meta.get("subject") == filt.get("subject")
        sys.modules["data_processor.metadata_extractor"] = MagicMock()
        sys.modules["data_processor.metadata_extractor"].MetadataExtractor = mock_extractor
        try:
            retriever = VectorRetriever()
            chunks = [
                make_chunk("c1", content="数学内容"),
                make_chunk("c2", content="物理内容"),
            ]
            chunks[0].metadata = {"subject": "数学"}
            chunks[1].metadata = {"subject": "物理"}
            retriever.build_index(chunks)

            retriever.vectorizer.embed_query = MagicMock(return_value=np.array([0.1, 0.2, 0.3]))
            retriever.vectorizer.cosine_similarity = MagicMock(return_value=0.8)

            results = retriever.search("query", top_k=5, metadata_filter={"subject": "数学"})
            assert len(results) == 1
            assert results[0].chunk.metadata["subject"] == "数学"
        finally:
            sys.modules.pop("data_processor.metadata_extractor", None)


class TestAddDocuments:
    def test_add_documents(self):
        from retriever.vector_retriever import VectorRetriever
        retriever = VectorRetriever()
        retriever.vectorizer.embed_documents = MagicMock(side_effect=lambda chunks: chunks)

        chunks = [make_chunk("c1"), make_chunk("c2")]
        retriever.add_documents(chunks)
        assert len(retriever._chunks) == 2

    def test_add_to_existing(self):
        from retriever.vector_retriever import VectorRetriever
        retriever = VectorRetriever()
        retriever.vectorizer.embed_documents = MagicMock(side_effect=lambda chunks: chunks)

        retriever.build_index([make_chunk("c1")])
        retriever.add_documents([make_chunk("c2"), make_chunk("c3")])
        assert len(retriever._chunks) == 3


class TestGetIndexStats:
    def test_empty_stats(self):
        from retriever.vector_retriever import VectorRetriever
        retriever = VectorRetriever()
        stats = retriever.get_index_stats()
        assert stats["num_documents"] == 0
        assert stats["type"] == "Vector"

    def test_after_build(self):
        from retriever.vector_retriever import VectorRetriever
        retriever = VectorRetriever()
        retriever.build_index([make_chunk("c1"), make_chunk("c2")])
        stats = retriever.get_index_stats()
        assert stats["num_documents"] == 2
