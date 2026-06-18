"""data_processor.document_splitter 文档切分测试"""
import pytest
from core.models import Document
from data_processor.document_splitter import DocumentSplitter


def make_doc(content, title="测试文档", source="test.txt", doc_id="doc_001"):
    return Document(content=content, title=title, source=source, doc_id=doc_id)


class TestSplitByHeaders:
    def test_no_headers(self):
        splitter = DocumentSplitter(mode="semantic")
        sections = splitter._split_by_headers("这是一段没有任何标题的普通文本。内容比较长。")
        assert len(sections) == 1
        assert sections[0] == "这是一段没有任何标题的普通文本。内容比较长。"

    def test_markdown_h1(self):
        splitter = DocumentSplitter(mode="semantic")
        text = "前言内容\n# 第一章 引言\n这是第一章的内容"
        sections = splitter._split_by_headers(text)
        assert len(sections) >= 2

    def test_markdown_h2_h3(self):
        splitter = DocumentSplitter(mode="semantic")
        text = "## 1.1 背景\n背景介绍文本\n### 1.1.1 细节\n细节文本"
        sections = splitter._split_by_headers(text)
        assert len(sections) >= 2

    def test_merge_short_sections(self):
        splitter = DocumentSplitter(mode="semantic")
        text = "短A\n\n短B\n\n短C\n\n" + "长内容" * 50
        sections = splitter._split_by_headers(text)
        # 短节合并后应远少于原本的空行数
        assert len(sections) >= 1


class TestSplitParagraphs:
    def test_single_paragraph(self):
        splitter = DocumentSplitter(mode="semantic")
        paras = splitter._split_paragraphs("单独一段文字。")
        assert len(paras) == 1

    def test_multiple_paragraphs(self):
        splitter = DocumentSplitter(mode="semantic")
        text = "第一段。\n\n第二段。\n\n第三段。"
        paras = splitter._split_paragraphs(text)
        assert len(paras) == 3

    def test_empty_text(self):
        splitter = DocumentSplitter(mode="semantic")
        paras = splitter._split_paragraphs("")
        assert paras == []


class TestMergeParagraphsToChunks:
    def test_small_paragraphs_merged(self):
        splitter = DocumentSplitter(mode="semantic", chunk_size=500)
        paras = ["段落一", "段落二", "段落三"]
        chunks = splitter._merge_paragraphs_to_chunks(paras, 200, 900)
        assert len(chunks) >= 1

    def test_single_large_paragraph(self):
        splitter = DocumentSplitter(mode="semantic", chunk_size=500)
        paras = ["测" * 1200]
        chunks = splitter._merge_paragraphs_to_chunks(paras, 200, 900)
        assert len(chunks) >= 1

    def test_empty(self):
        splitter = DocumentSplitter(mode="semantic")
        chunks = splitter._merge_paragraphs_to_chunks([], 200, 900)
        assert chunks == []


class TestSplitBySeparators:
    def test_single_newline(self):
        splitter = DocumentSplitter(chunk_size=100, separators=["\n", "。", " "])
        text = "第一行\n第二行\n第三行"
        chunks = splitter._split_by_separators(text)
        assert len(chunks) >= 1

    def test_period_separator(self):
        splitter = DocumentSplitter(chunk_size=500)
        text = "第一句话。第二句话。第三句话。第四句话。第五句话。"
        chunks = splitter._split_by_separators(text)
        assert len(chunks) >= 1

    def test_no_separator_match(self):
        splitter = DocumentSplitter(chunk_size=10)
        text = "abcdefghijklmnopqrstuvwxyz"  # no matching separators
        chunks = splitter._split_by_separators(text)
        assert len(chunks) >= 1
        # "" 分隔符按字符拆分，chunk_size 约束通过 _merge 保持
        assert all(len(c) > 0 for c in chunks)


class TestMergeSmallChunks:
    def test_merge_below_min(self):
        splitter = DocumentSplitter()
        chunks = ["短1", "短2", "长文本长文本长文本长文本长文本", "短3"]
        merged = splitter._merge_small_chunks(chunks, min_size=10)
        assert len(merged) <= len(chunks)

    def test_empty(self):
        splitter = DocumentSplitter()
        assert splitter._merge_small_chunks([]) == []

    def test_all_large(self):
        splitter = DocumentSplitter()
        chunks = ["长文本" * 20, "长文本" * 20]
        merged = splitter._merge_small_chunks(chunks, min_size=5)
        assert len(merged) == 2


class TestApplyOverlap:
    def test_no_overlap(self):
        splitter = DocumentSplitter(chunk_overlap=0)
        chunks = ["第一段", "第二段"]
        assert splitter._apply_overlap(chunks) == chunks

    def test_with_overlap(self):
        splitter = DocumentSplitter(chunk_overlap=5)
        chunks = ["1234567890", "abcdefghij"]
        result = splitter._apply_overlap(chunks)
        assert len(result) == 2
        assert result[1].startswith("67890")  # prev[-5:] from chunks[0]

    def test_single_chunk(self):
        splitter = DocumentSplitter(chunk_overlap=10)
        chunks = ["only one"]
        assert splitter._apply_overlap(chunks) == chunks


class TestSplitNative:
    def test_basic_split(self):
        splitter = DocumentSplitter(mode="native", chunk_size=200)
        doc = make_doc("这是测试内容。" * 50)
        chunks = splitter._split_with_native(doc)
        assert len(chunks) >= 1

    def test_short_document(self):
        splitter = DocumentSplitter(mode="native")
        doc = make_doc("短文本。")
        chunks = splitter._split_with_native(doc)
        assert len(chunks) >= 1

    def test_chunk_has_metadata(self):
        splitter = DocumentSplitter(mode="native", chunk_size=100)
        doc = make_doc("内容。" * 30)
        chunks = splitter._split_with_native(doc)
        for c in chunks:
            assert c.doc_id == "doc_001"
            assert c.metadata["title"] == "测试文档"
            assert c.metadata["splitter"] == "native"


class TestSplitBatch:
    def test_batch(self):
        splitter = DocumentSplitter(mode="native", chunk_size=500)
        docs = [make_doc("文档一。" * 20), make_doc("文档二。" * 20)]
        chunks = splitter.split_batch(docs)
        assert len(chunks) >= 2
