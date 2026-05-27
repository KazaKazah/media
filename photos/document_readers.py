import re
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile
import xml.etree.ElementTree as ET


class DocumentReadError(ValueError):
    pass


SUPPORTED_EXTENSIONS = {
    ".txt": "TXT",
    ".md": "Markdown",
    ".log": "LOG",
    ".csv": "CSV",
    ".json": "JSON",
    ".html": "HTML",
    ".htm": "HTML",
    ".xml": "XML",
    ".fb2": "FB2",
    ".docx": "Word DOCX",
    ".odt": "OpenDocument",
    ".epub": "EPUB",
    ".pdf": "PDF",
}


def compact_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def decode_plain_text(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "cp1251"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DocumentReadError("Не удалось прочитать текст: используйте UTF-8, UTF-16 или Windows-1251.")


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def element_text(element) -> str:
    return " ".join(" ".join(element.itertext()).split())


def extract_xml_paragraphs(payload: bytes, paragraph_tags: set[str], container_tag: str | None = None) -> str:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise DocumentReadError("Документ содержит повреждённый XML.") from error

    containers = [item for item in root.iter() if local_name(item.tag) == container_tag] if container_tag else [root]
    lines = []
    for container in containers:
        for item in container.iter():
            if local_name(item.tag) in paragraph_tags:
                text = element_text(item)
                if text:
                    lines.append(text)
    return "\n\n".join(lines)


class VisibleHTMLText(HTMLParser):
    BLOCK_TAGS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "br", "blockquote", "pre"}
    HIDDEN_TAGS = {"script", "style", "head", "svg"}

    def __init__(self):
        super().__init__()
        self.hidden_depth = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.HIDDEN_TAGS:
            self.hidden_depth += 1
        elif tag in self.BLOCK_TAGS and not self.hidden_depth:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.HIDDEN_TAGS:
            self.hidden_depth = max(0, self.hidden_depth - 1)
        elif tag in self.BLOCK_TAGS and not self.hidden_depth:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden_depth:
            self.parts.append(data)

    def text(self):
        return compact_text("".join(self.parts))


def read_html(payload: bytes) -> str:
    parser = VisibleHTMLText()
    parser.feed(decode_plain_text(payload))
    return parser.text()


def read_fb2(payload: bytes) -> str:
    return extract_xml_paragraphs(payload, {"p", "subtitle"}, "body")


def read_xml(payload: bytes) -> str:
    try:
        return compact_text(" ".join(ET.fromstring(payload).itertext()))
    except ET.ParseError as error:
        raise DocumentReadError("XML-файл повреждён или имеет неверный формат.") from error


def zip_member(archive: ZipFile, path: str) -> bytes:
    try:
        return archive.read(path)
    except KeyError as error:
        raise DocumentReadError("Документ повреждён: отсутствует необходимое содержимое.") from error


def read_docx(payload: bytes) -> str:
    try:
        with ZipFile(BytesIO(payload)) as archive:
            xml = zip_member(archive, "word/document.xml")
    except BadZipFile as error:
        raise DocumentReadError("Файл DOCX повреждён или не является документом Word.") from error
    return extract_xml_paragraphs(xml, {"p"})


def read_odt(payload: bytes) -> str:
    try:
        with ZipFile(BytesIO(payload)) as archive:
            xml = zip_member(archive, "content.xml")
    except BadZipFile as error:
        raise DocumentReadError("Файл ODT повреждён или имеет неверный формат.") from error
    return extract_xml_paragraphs(xml, {"p", "h"})


def read_epub(payload: bytes) -> str:
    try:
        with ZipFile(BytesIO(payload)) as archive:
            pages = [
                name for name in archive.namelist()
                if Path(name).suffix.lower() in {".html", ".htm", ".xhtml"}
            ]
            text = [read_html(archive.read(name)) for name in sorted(pages)]
    except BadZipFile as error:
        raise DocumentReadError("Файл EPUB повреждён или имеет неверный формат.") from error
    return "\n\n".join(page for page in text if page)


def read_pdf(payload: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(payload))
        if reader.is_encrypted and not reader.decrypt(""):
            raise DocumentReadError("PDF защищён паролем и не может быть прочитан.")
        return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)
    except DocumentReadError:
        raise
    except Exception as error:
        raise DocumentReadError("Не удалось извлечь текст из PDF-файла.") from error


def extract_document_text(filename: str, payload: bytes) -> str:
    extension = Path(filename).suffix.lower()
    if extension == ".doc":
        raise DocumentReadError("Старый формат .doc не поддерживается: сохраните файл как .docx.")
    if extension not in SUPPORTED_EXTENSIONS:
        raise DocumentReadError("Формат файла не поддерживается.")

    if extension in {".txt", ".md", ".log", ".csv", ".json"}:
        text = decode_plain_text(payload)
    elif extension in {".html", ".htm"}:
        text = read_html(payload)
    elif extension == ".xml":
        text = read_xml(payload)
    elif extension == ".fb2":
        text = read_fb2(payload)
    elif extension == ".docx":
        text = read_docx(payload)
    elif extension == ".odt":
        text = read_odt(payload)
    elif extension == ".epub":
        text = read_epub(payload)
    else:
        text = read_pdf(payload)

    text = compact_text(text)
    if not text:
        raise DocumentReadError("В документе не найден текст для чтения.")
    return text
