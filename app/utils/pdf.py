"""PDF parsing utility

Uses pdfplumber for text and table extraction.
Supports encrypted PDFs with password parameter.
"""

import io
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

import pdfplumber


@dataclass
class PDFPage:
    """single page data"""

    page_number: int
    text: str
    tables: list[list[list[str]]] = field(default_factory=list)
    width: float = 0
    height: float = 0


@dataclass
class PDFDocument:
    """parsed PDF document"""

    file_path: str
    total_pages: int
    pages: list[PDFPage] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        """get all text from the document"""
        return "\n\n".join(page.text for page in self.pages if page.text)

    @property
    def all_tables(self) -> list[list[list[str]]]:
        """get all tables from the document"""
        tables = []
        for page in self.pages:
            tables.extend(page.tables)
        return tables


class PDFParser:
    """PDF parser wrapper using pdfplumber

    Features:
        - Extract text and tables from PDF
        - Support encrypted PDFs with password
        - Parse from file path or bytes
        - Parse specific pages

    Usage:
        # parse entire document
        parser = PDFParser("path/to/file.pdf")
        doc = parser.parse()
        print(doc.full_text)

        # parse with password
        parser = PDFParser("encrypted.pdf", password="secret")
        doc = parser.parse()

        # parse specific pages
        doc = parser.parse(pages=[1, 2, 3])

        # extract tables only
        tables = parser.extract_tables()

        # parse from bytes (e.g., uploaded file)
        parser = PDFParser.from_bytes(pdf_bytes, password="secret")
        doc = parser.parse()
    """

    def __init__(self, file_path: str | Path, password: Optional[str] = None):
        """initialize parser with file path

        Args:
            file_path: path to PDF file
            password: password for encrypted PDF (optional)
        """
        self.file_path = Path(file_path)
        self._password = password
        self._pdf: Optional[pdfplumber.PDF] = None
        self._bytes_io: Optional[io.BytesIO] = None

    @classmethod
    def from_bytes(
        cls,
        pdf_bytes: bytes,
        filename: str = "memory.pdf",
        password: Optional[str] = None,
    ) -> "PDFParser":
        """create parser from bytes (e.g., uploaded file)

        Args:
            pdf_bytes: PDF file content as bytes
            filename: virtual filename for reference
            password: password for encrypted PDF (optional)

        Returns:
            PDFParser instance
        """
        parser = cls.__new__(cls)
        parser.file_path = Path(filename)
        parser._password = password
        parser._bytes_io = io.BytesIO(pdf_bytes)
        parser._pdf = None
        return parser

    def _open(self) -> pdfplumber.PDF:
        """open PDF file"""
        if self._pdf is None:
            if self._bytes_io:
                self._pdf = pdfplumber.open(self._bytes_io, password=self._password)
            else:
                self._pdf = pdfplumber.open(self.file_path, password=self._password)
        return self._pdf

    def close(self):
        """close PDF file"""
        if self._pdf:
            self._pdf.close()
            self._pdf = None
        if self._bytes_io:
            self._bytes_io.close()
            self._bytes_io = None

    def __enter__(self):
        self._open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def parse(
        self,
        pages: Optional[list[int]] = None,
        extract_tables: bool = True,
    ) -> PDFDocument:
        """parse PDF document

        Args:
            pages: list of page numbers to parse (1-based), None for all pages
            extract_tables: whether to extract tables

        Returns:
            PDFDocument with parsed content
        """
        pdf = self._open()

        doc = PDFDocument(
            file_path=str(self.file_path),
            total_pages=len(pdf.pages),
            metadata=pdf.metadata or {},
        )

        for i, page in enumerate(pdf.pages):
            page_num = i + 1  # 1-based page number

            # skip if not in requested pages
            if pages and page_num not in pages:
                continue

            # extract text
            text = page.extract_text() or ""

            # extract tables
            tables = []
            if extract_tables:
                raw_tables = page.extract_tables() or []
                for table in raw_tables:
                    # clean table cells
                    cleaned = [
                        [cell if cell else "" for cell in row] for row in table if row
                    ]
                    if cleaned:
                        tables.append(cleaned)

            pdf_page = PDFPage(
                page_number=page_num,
                text=text,
                tables=tables,
                width=page.width,
                height=page.height,
            )
            doc.pages.append(pdf_page)

        return doc

    def extract_text(self, pages: Optional[list[int]] = None) -> str:
        """extract text only

        Args:
            pages: list of page numbers (1-based), None for all

        Returns:
            extracted text
        """
        doc = self.parse(pages=pages, extract_tables=False)
        return doc.full_text

    def extract_tables(
        self, pages: Optional[list[int]] = None
    ) -> list[list[list[str]]]:
        """extract tables only

        Args:
            pages: list of page numbers (1-based), None for all

        Returns:
            list of tables (each table is a 2D list)
        """
        pdf = self._open()
        tables = []

        for i, page in enumerate(pdf.pages):
            page_num = i + 1
            if pages and page_num not in pages:
                continue

            raw_tables = page.extract_tables() or []
            for table in raw_tables:
                cleaned = [
                    [cell if cell else "" for cell in row] for row in table if row
                ]
                if cleaned:
                    tables.append(cleaned)

        return tables

    def get_page_count(self) -> int:
        """get total page count"""
        pdf = self._open()
        return len(pdf.pages)


# convenience functions
def parse_pdf(
    file_path: str | Path,
    password: Optional[str] = None,
) -> PDFDocument:
    """quick parse a PDF file

    Args:
        file_path: path to PDF file
        password: password for encrypted PDF (optional)

    Returns:
        PDFDocument with parsed content
    """
    with PDFParser(file_path, password=password) as parser:
        return parser.parse()


def parse_pdf_bytes(
    pdf_bytes: bytes,
    password: Optional[str] = None,
) -> PDFDocument:
    """quick parse PDF from bytes

    Args:
        pdf_bytes: PDF content as bytes
        password: password for encrypted PDF (optional)

    Returns:
        PDFDocument with parsed content
    """
    parser = PDFParser.from_bytes(pdf_bytes, password=password)
    try:
        return parser.parse()
    finally:
        parser.close()
