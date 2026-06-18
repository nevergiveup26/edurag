"""data_processor.vectorizer 向量化处理测试"""
import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from core.models import DocumentChunk


class TestVectorizerInit:
    def test_init_with_config(self):
        from data_processor.vectorizer import Vectorizer
        v = Vectorizer()
        assert v._provider == "dashscope"
        assert v.embedding_dim == 1024
        assert v._model_name == "text-embedding-v4"

    def test_list_models(self):
        from data_processor.vectorizer import Vectorizer
        models = Vectorizer.list_models()
        assert len(models) == 1
        assert models[0]["dim"] == 1024


class TestCosineSimilarity:
    def test_identical_vectors(self):
        from data_processor.vectorizer import Vectorizer
        v = Vectorizer()
        vec = [1.0, 0.0, 0.0]
        sim = v.cosine_similarity(vec, vec)
        assert sim == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        from data_processor.vectorizer import Vectorizer
        v = Vectorizer()
        sim = v.cosine_similarity([1.0, 0.0], [0.0, 1.0])
        assert sim == pytest.approx(0.0)

    def test_opposite_vectors(self):
        from data_processor.vectorizer import Vectorizer
        v = Vectorizer()
        sim = v.cosine_similarity([1.0, 2.0], [-1.0, -2.0])
        assert sim == pytest.approx(-1.0)

    def test_zero_vector(self):
        from data_processor.vectorizer import Vectorizer
        v = Vectorizer()
        sim = v.cosine_similarity([0.0, 0.0], [1.0, 2.0])
        assert sim == 0.0

    def test_both_zero_vectors(self):
        from data_processor.vectorizer import Vectorizer
        v = Vectorizer()
        sim = v.cosine_similarity([0.0, 0.0], [0.0, 0.0])
        assert sim == 0.0

    def test_positive_similarity(self):
        from data_processor.vectorizer import Vectorizer
        v = Vectorizer()
        sim = v.cosine_similarity([1.0, 2.0, 3.0], [2.0, 4.0, 6.0])
        assert sim == pytest.approx(1.0)  # 同方向


class TestEmbedQuery:
    def test_embed_query(self):
        from data_processor.vectorizer import Vectorizer
        v = Vectorizer()
        mock_embeddings = [[0.1, 0.2, 0.3]]
        v.embed = MagicMock(return_value=mock_embeddings)
        result = v.embed_query("test")
        assert result == [0.1, 0.2, 0.3]
        v.embed.assert_called_once_with(["test"])


class TestEmbedDocuments:
    def test_embed_documents(self):
        from data_processor.vectorizer import Vectorizer
        v = Vectorizer()
        mock_embeddings = [[0.1, 0.2], [0.3, 0.4]]
        v.embed = MagicMock(return_value=mock_embeddings)

        chunks = [
            DocumentChunk(chunk_id="c1", doc_id="d1", content="hello", metadata={}),
            DocumentChunk(chunk_id="c2", doc_id="d1", content="world", metadata={}),
        ]
        result = v.embed_documents(chunks)
        assert len(result) == 2
        assert result[0].embedding == [0.1, 0.2]
        assert result[1].embedding == [0.3, 0.4]


class TestProvider:
    def test_provider_name(self):
        from data_processor.vectorizer import Vectorizer
        v = Vectorizer()
        assert v.provider == "dashscope"

    def test_model_name(self):
        from data_processor.vectorizer import Vectorizer
        v = Vectorizer()
        assert v.model_name == "text-embedding-v4"


class TestEmbedCloud:
    def test_single_batch(self):
        from data_processor.vectorizer import Vectorizer
        v = Vectorizer()
        v._batch_size = 10
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.data = [MagicMock(embedding=[0.1, 0.2]), MagicMock(embedding=[0.3, 0.4])]
        mock_client.embeddings.create.return_value = mock_resp
        v._client = mock_client
        v._client_ready = True

        embeddings = v._embed_cloud(["text1", "text2"])
        assert len(embeddings) == 2
        assert embeddings[0] == [0.1, 0.2]

    def test_multiple_batches(self):
        from data_processor.vectorizer import Vectorizer
        v = Vectorizer()
        v._batch_size = 2
        mock_client = MagicMock()

        def make_resp(**kwargs):
            input_texts = kwargs.get("input", [])
            resp = MagicMock()
            resp.data = [MagicMock(embedding=[0.1]) for _ in input_texts]
            return resp

        mock_client.embeddings.create.side_effect = make_resp
        v._client = mock_client
        v._client_ready = True

        embeddings = v._embed_cloud(["t1", "t2", "t3", "t4"])
        assert len(embeddings) == 4
        assert mock_client.embeddings.create.call_count == 2  # 4/2 = 2 batches

    def test_retry_then_success(self):
        from data_processor.vectorizer import Vectorizer
        v = Vectorizer()
        v._batch_size = 10
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.data = [MagicMock(embedding=[0.1])]
        # 前两次失败，第三次成功
        mock_client.embeddings.create.side_effect = [
            Exception("fail1"), Exception("fail2"), mock_resp,
        ]
        v._client = mock_client
        v._client_ready = True

        embeddings = v._embed_cloud(["text1"])
        assert len(embeddings) == 1

    def test_all_retries_exhausted(self):
        from data_processor.vectorizer import Vectorizer
        v = Vectorizer()
        v._batch_size = 10
        mock_client = MagicMock()
        mock_client.embeddings.create.side_effect = Exception("always fail")
        v._client = mock_client
        v._client_ready = True

        with pytest.raises(RuntimeError, match="重试3次后仍失败"):
            v._embed_cloud(["text1"])
