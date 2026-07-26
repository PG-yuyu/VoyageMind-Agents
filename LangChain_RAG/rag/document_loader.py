"""文档文件读取 —— 支持 PDF、DOCX、TXT 格式。

读取原始文本和元数据（页码、标题等），不负责清洗和切块。
"""

import hashlib
import logging
import os
from dataclasses import dataclass, field

from contracts.errors import (
    DOCUMENT_PARSE_FAILED,
    INVALID_FILE_TYPE,
    ServiceError,
)

logger = logging.getLogger("rag.document_loader")


@dataclass
class PageInfo:
    """单页信息。"""
    page_number: int
    text: str


@dataclass
class DocumentLoadResult:
    """文档加载结果（原始内容 + 元数据）。"""
    content: str
    pages: list[PageInfo] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class DocumentLoader:
    """读取 PDF、DOCX、TXT 文档，返回原始文本和页级元数据。"""

    SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}

    def load(self, file_path: str) -> DocumentLoadResult:
        """根据扩展名分派到对应的加载器。

        Raises:
            ServiceError(INVALID_FILE_TYPE): 不支持的文件格式。
            ServiceError(DOCUMENT_PARSE_FAILED): 文档解析失败。
        """
        if not os.path.isfile(file_path):
            raise ServiceError(
                code=DOCUMENT_PARSE_FAILED,
                message=f"文件不存在: {file_path}",
            )

        ext = os.path.splitext(file_path)[1].lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            raise ServiceError(
                code=INVALID_FILE_TYPE,
                message=f"不支持的文件格式: {ext}，支持的格式: {', '.join(sorted(self.SUPPORTED_EXTENSIONS))}",
            )

        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        base_meta = {
            "filename": filename,
            "file_path": file_path,
            "file_size": file_size,
            "extension": ext,
        }

        try:
            if ext == ".pdf":
                result = self._load_pdf(file_path)
            elif ext == ".docx":
                result = self._load_docx(file_path)
            elif ext in {".txt", ".md"}:
                result = self._load_txt(file_path)
            else:
                # 已经在前面的检查中排除，这里是防御性代码
                raise ServiceError(code=INVALID_FILE_TYPE, message=f"不支持的文件格式: {ext}")
        except ServiceError:
            raise
        except Exception as e:
            logger.exception("Document parsing failed: %s", file_path)
            raise ServiceError(
                code=DOCUMENT_PARSE_FAILED,
                message=f"文档解析失败 ({filename}): {e}",
                details={"file_path": file_path, "error": str(e)},
            ) from e

        result.metadata.update(base_meta)
        logger.info("Loaded document: %s, chars=%d, pages=%d", filename, len(result.content), len(result.pages))
        return result

    # ── PDF ─────────────────────────────────────────────────

    def _load_pdf(self, file_path: str) -> DocumentLoadResult:
        """使用 PyMuPDF (fitz) 读取 PDF，fallback 到 pdfplumber / PyPDF2。"""
        pages: list[PageInfo] = []
        full_text_parts: list[str] = []

        # 优先使用 PyMuPDF
        try:
            import fitz  # type: ignore[import-untyped]
            doc = fitz.open(file_path)
            for i, page in enumerate(doc, start=1):
                text = page.get_text()
                pages.append(PageInfo(page_number=i, text=text))
                full_text_parts.append(text)
            doc.close()
            return DocumentLoadResult(
                content="\n\n".join(full_text_parts),
                pages=pages,
            )
        except ImportError:
            logger.debug("PyMuPDF not available, trying pdfplumber")
        except Exception as e:
            logger.warning("PyMuPDF failed: %s, trying fallback", e)

        # Fallback 1: pdfplumber
        try:
            import pdfplumber  # type: ignore[import-untyped]
            with pdfplumber.open(file_path) as pdf:
                for i, page in enumerate(pdf.pages, start=1):
                    text = page.extract_text() or ""
                    pages.append(PageInfo(page_number=i, text=text))
                    full_text_parts.append(text)
            return DocumentLoadResult(
                content="\n\n".join(full_text_parts),
                pages=pages,
            )
        except ImportError:
            logger.debug("pdfplumber not available, trying PyPDF2")
        except Exception as e:
            logger.warning("pdfplumber failed: %s, trying PyPDF2", e)

        # Fallback 2: PyPDF2
        try:
            from PyPDF2 import PdfReader  # type: ignore[import-untyped]
            reader = PdfReader(file_path)
            for i, page in enumerate(reader.pages, start=1):
                text = page.extract_text() or ""
                pages.append(PageInfo(page_number=i, text=text))
                full_text_parts.append(text)
            return DocumentLoadResult(
                content="\n\n".join(full_text_parts),
                pages=pages,
            )
        except ImportError:
            raise ServiceError(
                code=DOCUMENT_PARSE_FAILED,
                message="未安装 PDF 解析库，请安装 PyMuPDF、pdfplumber 或 PyPDF2",
            )

    # ── DOCX ────────────────────────────────────────────────

    def _load_docx(self, file_path: str) -> DocumentLoadResult:
        """使用 python-docx 读取 Word 文档。"""
        try:
            from docx import Document  # type: ignore[import-untyped]
        except ImportError:
            raise ServiceError(
                code=DOCUMENT_PARSE_FAILED,
                message="未安装 python-docx，请执行: pip install python-docx",
            )

        doc = Document(file_path)
        paragraphs: list[str] = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                # 检测标题样式，用 markdown 标记保留结构
                if para.style and para.style.name and para.style.name.startswith("Heading"):
                    level = para.style.name.split()[-1]
                    try:
                        level_num = int(level)
                        text = "#" * min(level_num, 4) + " " + text
                    except ValueError:
                        text = "## " + text
                paragraphs.append(text)

        content = "\n\n".join(paragraphs)
        return DocumentLoadResult(
            content=content,
            pages=[PageInfo(page_number=1, text=content)],
        )

    # ── TXT ─────────────────────────────────────────────────

    def _load_txt(self, file_path: str) -> DocumentLoadResult:
        """读取纯文本文件，自动检测编码。"""
        content = None
        for encoding in ("utf-8", "gbk", "gb2312", "latin-1"):
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    content = f.read()
                break
            except UnicodeDecodeError:
                continue

        if content is None:
            raise ServiceError(
                code=DOCUMENT_PARSE_FAILED,
                message="无法识别文本编码，请确认文件为 UTF-8 或 GBK 编码",
            )

        return DocumentLoadResult(
            content=content,
            pages=[PageInfo(page_number=1, text=content)],
        )


def compute_file_hash(file_path: str, algorithm: str = "sha256") -> str:
    """计算文件哈希值，用于生成稳定的 document_id。"""
    h = hashlib.new(algorithm)
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
