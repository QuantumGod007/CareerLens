"""Isolated PDF parser. Bounded stdin/stdout; never emits document text on failure."""
import io
import json
import resource
import sys

MAX_BYTES = 5 * 1024 * 1024
MAX_TEXT = 80000


def parse(data, max_pages=10):
    if len(data) > MAX_BYTES:
        return {"error": "PDF_TOO_LARGE"}
    if not data.startswith(b"%PDF-"):
        return {"error": "UNREADABLE_PDF"}
    import pdfplumber
    from pypdf import PdfReader, Configuration, overwrite_configuration
    configuration = Configuration(maximum_declared_stream_length=8 * 1024 * 1024,
        zlib_maximum_output_length=8 * 1024 * 1024, array_based_stream_maximum_output_length=8 * 1024 * 1024,
        lzw_maximum_output_length=8*1024*1024, run_length_maximum_output_length=8*1024*1024,
        stream_decoding_work_maximum_length=32*1024*1024, stream_parsing_work_maximum_count=500000,
        page_tree_maximum_entries=100, xform_maximum_invocations_per_extraction=100)
    try:
        overwrite_configuration(configuration)
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            return {"error": "ENCRYPTED_PDF"}
        count = len(reader.pages)
        if not count:
            return {"error": "EMPTY_PDF"}
        if count > max_pages:
            return {"error": "TOO_MANY_PAGES"}
        # Exercise bounded stream decoding before the independent layout extractor.
        for page in reader.pages:
            if len(page.extract_text()) > MAX_TEXT:
                return {"error": "PDF_TEXT_LIMIT"}
        # Reject active content and embedded files; the original PDF is never rendered as a web page.
        root = reader.trailer["/Root"]
        names = root.get("/Names", {})
        names = names.get_object() if hasattr(names,"get_object") else names
        if (any(key in root for key in ("/OpenAction", "/AA"))
                or any(key in names for key in ("/JavaScript","/EmbeddedFiles"))
                or any('/AA' in page for page in reader.pages)):
            return {"error": "UNSUPPORTED_PDF_CONTENT"}
        pages, total = [], 0
        with pdfplumber.open(io.BytesIO(data)) as document:
            for index, page in enumerate(document.pages, 1):
                if page.width > 3000 or page.height > 3000:
                    return {"error": "PDF_RESOURCE_LIMIT"}
                text = page.extract_text() or ""
                total += len(text)
                if total > MAX_TEXT or len(page.chars) > 30000:
                    return {"error": "PDF_TEXT_LIMIT"}
                pages.append({"page": index, "text": text, "start_offset": 0, "end_offset": len(text)})
        if not any(page["text"].strip() for page in pages):
            return {"error": "NO_EXTRACTABLE_TEXT"}
        return {"pages": pages}
    except Exception:
        return {"error": "UNREADABLE_PDF"}


def main():
    # Parsing libraries operate in a disposable process, outside the worker and API.
    resource.setrlimit(resource.RLIMIT_CPU, (12, 12))
    # macOS can reject memory rlimits; the parent also monitors process-tree RSS.
    try:
        resource.setrlimit(resource.RLIMIT_DATA, (512 * 1024 * 1024, 512 * 1024 * 1024))
    except (ValueError, OSError):
        pass
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    data = sys.stdin.buffer.read(MAX_BYTES + 1)
    result = parse(data, int(sys.argv[1]) if len(sys.argv) > 1 else 10)
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
