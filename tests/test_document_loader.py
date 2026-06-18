"""data_processor.document_loader 文档加载器测试"""
import os
import pytest
from unittest.mock import MagicMock, patch


class TestSupportedExtensions:
    def test_has_common_formats(self):
        from data_processor.document_loader import DocumentLoader
        assert ".txt" in DocumentLoader.SUPPORTED_EXTENSIONS
        assert ".pdf" in DocumentLoader.SUPPORTED_EXTENSIONS
        assert ".docx" in DocumentLoader.SUPPORTED_EXTENSIONS
        assert ".csv" in DocumentLoader.SUPPORTED_EXTENSIONS
        assert ".json" in DocumentLoader.SUPPORTED_EXTENSIONS


class TestLoadTxt:
    def test_load_txt(self, tmp_path):
        from data_processor.document_loader import DocumentLoader
        filepath = tmp_path / "test.txt"
        filepath.write_text("这是测试内容。", encoding="utf-8")

        docs = DocumentLoader._load_txt(str(filepath))
        assert len(docs) == 1
        assert docs[0].content == "这是测试内容。"
        assert docs[0].doc_id == "test.txt"


class TestLoadCsv:
    def test_load_csv(self, tmp_path):
        from data_processor.document_loader import DocumentLoader
        filepath = tmp_path / "test.csv"
        filepath.write_text("a,b,c\n1,2,3\n4,5,6", encoding="utf-8")

        docs = DocumentLoader._load_csv(str(filepath))
        assert len(docs) == 2


class TestLoadJson:
    def test_load_json(self, tmp_path):
        from data_processor.document_loader import DocumentLoader
        filepath = tmp_path / "test.json"
        filepath.write_text('{"key": "value"}', encoding="utf-8")

        docs = DocumentLoader._load_json(str(filepath))
        assert len(docs) == 1
        assert docs[0].doc_id == "test.json"


class TestLoadWithNative:
    def test_dispatches_to_txt(self, tmp_path):
        from data_processor.document_loader import DocumentLoader
        filepath = tmp_path / "test.txt"
        filepath.write_text("hello", encoding="utf-8")

        docs = DocumentLoader._load_with_native(str(filepath), ".txt")
        assert len(docs) == 1

    def test_dispatches_to_csv(self, tmp_path):
        from data_processor.document_loader import DocumentLoader
        filepath = tmp_path / "test.csv"
        filepath.write_text("a,b\n1,2", encoding="utf-8")

        docs = DocumentLoader._load_with_native(str(filepath), ".csv")
        assert len(docs) == 1

    def test_dispatches_to_json(self, tmp_path):
        from data_processor.document_loader import DocumentLoader
        filepath = tmp_path / "test.json"
        filepath.write_text('{"x":1}', encoding="utf-8")

        docs = DocumentLoader._load_with_native(str(filepath), ".json")
        assert len(docs) == 1

    def test_dispatches_to_pdf(self, tmp_path):
        import sys
        mock_pypdf2 = MagicMock()
        mock_reader = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "pdf content"
        mock_reader.pages = [mock_page]
        mock_pypdf2.PdfReader.return_value = mock_reader
        sys.modules["PyPDF2"] = mock_pypdf2
        try:
            from data_processor.document_loader import DocumentLoader
            filepath = tmp_path / "test.pdf"
            filepath.write_text("", encoding="utf-8")  # 创建空文件
            docs = DocumentLoader._load_with_native(str(filepath), ".pdf")
            assert len(docs) == 1
            assert docs[0].content == "pdf content"
        finally:
            sys.modules.pop("PyPDF2", None)

    def test_dispatches_to_word(self, tmp_path):
        import sys
        mock_docx = MagicMock()
        mock_doc = MagicMock()
        mock_doc.paragraphs = []
        mock_docx.Document.return_value = mock_doc
        sys.modules["docx"] = mock_docx
        try:
            from data_processor.document_loader import DocumentLoader
            filepath = tmp_path / "test.docx"
            filepath.write_text("", encoding="utf-8")
            docs = DocumentLoader._load_with_native(str(filepath), ".docx")
            assert len(docs) == 1
        finally:
            sys.modules.pop("docx", None)

    def test_unsupported_ext_in_native(self, tmp_path):
        from data_processor.document_loader import DocumentLoader
        with pytest.raises(ValueError, match="不支持的文件格式"):
            DocumentLoader._load_with_native("test.xyz", ".xyz")


class TestLoadFile:
    def test_valid_ext_loads(self, tmp_path):
        from data_processor.document_loader import DocumentLoader
        filepath = tmp_path / "test.txt"
        filepath.write_text("content", encoding="utf-8")
        docs = DocumentLoader.load_file(str(filepath))
        assert len(docs) == 1

    def test_invalid_ext_raises(self):
        from data_processor.document_loader import DocumentLoader
        with pytest.raises(ValueError, match="不支持的文件格式"):
            DocumentLoader.load_file("test.xyz")

    def test_langchain_fallback_to_native(self, tmp_path):
        from data_processor.document_loader import DocumentLoader
        filepath = tmp_path / "test.txt"
        filepath.write_text("content", encoding="utf-8")

        with patch.object(DocumentLoader, "_load_with_langchain",
                          side_effect=Exception("langchain error")):
            docs = DocumentLoader.load_file(str(filepath))
            assert len(docs) == 1


class TestLoadDirectory:
    def test_load_directory(self, tmp_path):
        from data_processor.document_loader import DocumentLoader
        (tmp_path / "a.txt").write_text("aaa", encoding="utf-8")
        (tmp_path / "b.txt").write_text("bbb", encoding="utf-8")

        docs = DocumentLoader.load_directory(str(tmp_path), recursive=False)
        assert len(docs) == 2

    def test_load_directory_filter_extensions(self, tmp_path):
        from data_processor.document_loader import DocumentLoader
        (tmp_path / "a.txt").write_text("aaa", encoding="utf-8")
        (tmp_path / "b.csv").write_text("a,b\n1,2", encoding="utf-8")

        docs = DocumentLoader.load_directory(str(tmp_path), extensions=[".csv"], recursive=False)
        assert len(docs) == 1

    def test_load_directory_skips_unsupported(self, tmp_path):
        from data_processor.document_loader import DocumentLoader
        (tmp_path / "a.txt").write_text("aaa", encoding="utf-8")
        (tmp_path / "image.png").write_text("not a text file", encoding="utf-8")

        docs = DocumentLoader.load_directory(str(tmp_path), recursive=False)
        assert len(docs) == 1
