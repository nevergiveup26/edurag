"""
文档智能切分
集成 LangChain 文本切分器 + 语义感知切分 + 原生实现多模式
支持按标题/段落/句子切分，重叠窗口，语义完整性保护
"""
import re
import uuid
from typing import List

from core.models import Document, DocumentChunk
from core.logger import get_logger

logger = get_logger("document_splitter")


class DocumentSplitter:
    """文档智能切分器（LangChain + 语义感知 + 原生多模式）

    支持三种切分模式:
    - semantic:  语义感知切分（推荐），识别标题/段落结构，800-1200字符
    - langchain: LangChain RecursiveCharacterTextSplitter
    - native:    原生分隔符切分（fallback）
    """

    MODES = ("semantic", "langchain", "native")

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50,
                 separators: List[str] = None, mode: str = "semantic"):
        """
        Args:
            chunk_size: 每个片段的目标字符数
            chunk_overlap: 片段重叠字符数
            separators: 自定义分隔符（优先级从高到低）
            mode: 切分模式 "semantic" | "langchain" | "native"
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.mode = mode if mode in self.MODES else "semantic"
        self.separators = separators or ["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""]

    def split(self, document: Document) -> List[DocumentChunk]:
        """切分单个文档，按模式路由"""
        if self.mode == "semantic":
            try:
                return self._split_semantic(document)
            except Exception as e:
                logger.debug(f"语义切分失败，回退到langchain: {e}")
                return self._split_with_langchain(document)
        elif self.mode == "langchain":
            try:
                return self._split_with_langchain(document)
            except Exception as e:
                logger.debug(f"LangChain 切分失败，回退到原生切分: {e}")
                return self._split_with_native(document)
        else:
            return self._split_with_native(document)

    def split_batch(self, documents: List[Document]) -> List[DocumentChunk]:
        """批量切分文档"""
        all_chunks = []
        for doc in documents:
            chunks = self.split(doc)
            all_chunks.extend(chunks)
        logger.info(f"批量切分完成: {len(documents)} 个文档 → {len(all_chunks)} 个片段")
        return all_chunks

    def _split_with_langchain(self, document: Document) -> List[DocumentChunk]:
        """使用 LangChain RecursiveCharacterTextSplitter 切分"""
        from langchain.text_splitter import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=self.separators,
            length_function=len,
        )
        lc_docs = splitter.create_documents(
            texts=[document.content],
            metadatas=[{
                "title": document.title,
                "source": document.source,
                "doc_id": document.doc_id,
                "splitter": "langchain",
            }],
        )

        doc_chunks = []
        for i, lc_doc in enumerate(lc_docs):
            chunk_id = f"{document.doc_id}_chunk_{i}"
            doc_chunks.append(DocumentChunk(
                content=lc_doc.page_content,
                chunk_id=chunk_id,
                doc_id=document.doc_id,
                metadata={
                    "chunk_index": i,
                    "title": document.title,
                    "source": document.source,
                    **document.metadata,
                    **dict(lc_doc.metadata),
                },
            ))

        logger.info(f"[LangChain] 文档切分: {document.doc_id} → {len(doc_chunks)} 片段")
        return doc_chunks

    def _split_with_native(self, document: Document) -> List[DocumentChunk]:
        """原生切分实现（fallback）"""
        content = document.content
        chunks = self._split_by_separators(content)
        chunks = self._merge_small_chunks(chunks)

        if self.chunk_overlap > 0:
            chunks = self._apply_overlap(chunks)

        doc_chunks = []
        for i, chunk_text in enumerate(chunks):
            doc_chunks.append(DocumentChunk(
                content=chunk_text,
                chunk_id=f"{document.doc_id}_chunk_{i}",
                doc_id=document.doc_id,
                metadata={
                    "chunk_index": i,
                    "title": document.title,
                    "source": document.source,
                    "splitter": "native",
                    **document.metadata,
                },
            ))

        logger.info(f"[原生] 文档切分: {document.doc_id} → {len(doc_chunks)} 片段")
        return doc_chunks

    # ========== 语义感知切分 ==========

    # Markdown/文档标题模式
    HEADER_PATTERN = re.compile(r'^#{1,3}\s+(.+)$', re.MULTILINE)
    # 段落间空行
    SECTION_BREAK = re.compile(r'\n\s*\n')

    def _split_semantic(self, document: Document) -> List[DocumentChunk]:
        """
        语义感知切分

        策略:
        1. 识别 Markdown 标题 (# ## ###)，作为自然分割点
        2. 段落间空行作为次级分割点
        3. 保持句子完整性（句号、问号、感叹号结尾）
        4. 目标大小: 800-1200 字符（比旧的500更丰富）
        5. 重叠: 前一个chunk的最后一段
        """
        content = document.content
        target_min = max(400, self.chunk_size - 300)
        target_max = self.chunk_size + 400

        # Step 1: 按标题分节
        sections = self._split_by_headers(content)
        if not sections:
            sections = [content]

        # Step 2: 每个节按段落分块
        raw_chunks = []
        for section_text in sections:
            paragraphs = self._split_paragraphs(section_text)
            raw_chunks.extend(self._merge_paragraphs_to_chunks(paragraphs, target_min, target_max))

        # Step 3: 构建 DocumentChunk 带重叠
        doc_chunks = []
        prev_tail = ""
        for i, chunk_text in enumerate(raw_chunks):
            if i > 0 and self.chunk_overlap > 0 and prev_tail:
                chunk_text = prev_tail + "\n" + chunk_text
            doc_chunks.append(DocumentChunk(
                content=chunk_text.strip(),
                chunk_id=f"{document.doc_id}_chunk_{i}",
                doc_id=document.doc_id,
                metadata={
                    "chunk_index": i,
                    "title": document.title,
                    "source": document.source,
                    "splitter": "semantic",
                    "chunk_count": 0,  # will be filled after splitting
                    **document.metadata,
                },
            ))
            # 保存末尾作为下一个 chunk 的重叠内容
            sentences = re.split(r'[。！？!?]+', chunk_text)
            if len(sentences) >= 2:
                prev_tail = sentences[-2][-self.chunk_overlap:] if len(sentences[-2]) >= self.chunk_overlap else sentences[-2]
            else:
                prev_tail = ""

        # 填充 chunk_count
        for c in doc_chunks:
            c.metadata["chunk_count"] = len(doc_chunks)

        logger.info(f"[语义] 文档切分: {document.doc_id} → {len(doc_chunks)} 片段 "
                    f"(avg={sum(len(c.content) for c in doc_chunks)//max(len(doc_chunks),1)}字符)")
        return doc_chunks

    def _split_by_headers(self, text: str) -> List[str]:
        """按 Markdown 标题分割文档"""
        matches = list(self.HEADER_PATTERN.finditer(text))
        if not matches:
            # 没有标题，用空行分割大段
            big_sections = self.SECTION_BREAK.split(text)
            # 合并短节
            merged = []
            current = ""
            for s in big_sections:
                if len(current) < 300:
                    current += "\n\n" + s if current else s
                else:
                    merged.append(current)
                    current = s
            if current:
                merged.append(current)
            return merged if merged else [text]

        sections = []
        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            sections.append(text[start:end])
        # 标题前的内容
        if matches and matches[0].start() > 0:
            prefix = text[:matches[0].start()].strip()
            if prefix:
                sections.insert(0, prefix)
        return sections

    def _split_paragraphs(self, text: str) -> List[str]:
        """按段落分割文本（保留标题）"""
        parts = self.SECTION_BREAK.split(text.strip())
        return [p.strip() for p in parts if p.strip()]

    def _merge_paragraphs_to_chunks(self, paragraphs: List[str],
                                     target_min: int, target_max: int) -> List[str]:
        """将段落合并为接近目标大小的 chunk，保护句子边界"""
        chunks = []
        current = ""
        for para in paragraphs:
            tentative = current + ("\n\n" if current else "") + para
            if len(tentative) <= target_max:
                current = tentative
            else:
                if current:
                    chunks.append(current)
                # 如果单个段落就超过 target_max，按句子进一步拆分
                if len(para) > target_max:
                    chunks.extend(self._split_long_paragraph(para, target_min, target_max))
                    current = ""
                else:
                    current = para
        if current:
            chunks.append(current)
        return chunks

    def _split_long_paragraph(self, text: str, target_min: int, target_max: int) -> List[str]:
        """对超长段落按句子拆分"""
        sentences = re.split(r'(?<=[。！？!?])\s*', text)
        chunks = []
        current = ""
        for sent in sentences:
            tentative = current + sent
            if len(tentative) <= target_max:
                current = tentative
            else:
                if current:
                    chunks.append(current)
                current = sent
        if current:
            chunks.append(current)
        return chunks

    def _split_by_separators(self, text: str) -> List[str]:
        """按分隔符递归切分"""
        chunks = [text]
        for sep in self.separators:
            if not sep:
                continue
            new_chunks = []
            for chunk in chunks:
                if len(chunk) <= self.chunk_size:
                    new_chunks.append(chunk)
                else:
                    parts = chunk.split(sep)
                    merged = []
                    current = ""
                    for part in parts:
                        if len(current) + len(part) + len(sep) <= self.chunk_size:
                            current += (sep if current else "") + part
                        else:
                            if current:
                                merged.append(current)
                            current = part
                    if current:
                        merged.append(current)
                    new_chunks.extend(merged)
            chunks = new_chunks
        return [c.strip() for c in chunks if c.strip()]

    def _merge_small_chunks(self, chunks: List[str], min_size: int = 100) -> List[str]:
        """合并过小的片段"""
        if not chunks:
            return chunks
        merged = [chunks[0]]
        for chunk in chunks[1:]:
            if len(merged[-1]) < min_size:
                merged[-1] += "\n" + chunk
            else:
                merged.append(chunk)
        return merged

    def _apply_overlap(self, chunks: List[str]) -> List[str]:
        """应用片段重叠"""
        if self.chunk_overlap <= 0 or len(chunks) <= 1:
            return chunks
        overlapped = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_chunk = chunks[i - 1]
            current_chunk = chunks[i]
            overlap_text = prev_chunk[-self.chunk_overlap:]
            overlapped.append(overlap_text + current_chunk)
        return overlapped