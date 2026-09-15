"""文档解析：把上传的二进制文件转成纯文本，再交给入库流程。

支持 txt / markdown / PDF / DOCX。解析失败要报出**人能看懂**的原因：
扫描版 PDF 抽不到文字、加密 PDF 读不了、文件类型不支持——这三种情况
用户能自己处理，不该只看到一个 500。
"""

import io
from pathlib import PurePosixPath

from docx import Document as DocxDocument
from pypdf import PdfReader

TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".text", ".log", ".csv"}
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | {".pdf", ".docx"}


class UnsupportedDocument(Exception):
    """文件类型不支持。"""


class DocumentParseError(Exception):
    """文件类型支持，但内容读不出来（加密、损坏、扫描件等）。"""


def detect_suffix(filename: str) -> str:
    return PurePosixPath(filename.replace("\\", "/")).suffix.lower()


def extract_text(filename: str, content: bytes) -> str:
    """按扩展名分派解析器，返回纯文本。"""
    suffix = detect_suffix(filename)

    if suffix in TEXT_SUFFIXES:
        return _extract_plain_text(content)
    if suffix == ".pdf":
        return _extract_pdf(content)
    if suffix == ".docx":
        return _extract_docx(content)

    raise UnsupportedDocument(
        f"暂不支持 {suffix or '该'} 格式。目前支持：txt、markdown、PDF、DOCX"
    )


def _extract_plain_text(content: bytes) -> str:
    # 中文文本常见 UTF-8；退回 GBK 覆盖 Windows 上导出的老文件
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _extract_pdf(content: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as exc:  # noqa: BLE001 加密或损坏都归到这里
        raise DocumentParseError(f"PDF 打不开：{type(exc).__name__}: {exc}") from exc

    if reader.is_encrypted:
        raise DocumentParseError("PDF 有密码保护，请先去掉密码再上传")

    pages: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001 单页损坏不该让整个文件失败
            text = ""
            pages.append(f"[第 {index} 页解析失败：{type(exc).__name__}]")
        if text.strip():
            pages.append(text.strip())

    joined = "\n\n".join(pages).strip()
    if not joined:
        raise DocumentParseError(
            "PDF 里没有可提取的文字（可能是扫描件）。OCR 不在支持范围内，"
            "请先用工具把扫描件转成文本再上传。"
        )
    return joined


def _extract_docx(content: bytes) -> str:
    try:
        document = DocxDocument(io.BytesIO(content))
    except Exception as exc:  # noqa: BLE001
        raise DocumentParseError(f"DOCX 打不开：{type(exc).__name__}: {exc}") from exc

    parts = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]

    # 表格里的文字也算正文：很多说明文档把关键信息放在表格里
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))

    joined = "\n\n".join(parts).strip()
    if not joined:
        raise DocumentParseError("DOCX 里没有可提取的文字")
    return joined
