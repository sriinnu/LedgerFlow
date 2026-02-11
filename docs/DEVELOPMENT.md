# Development

## Requirements

- Python 3.11+ recommended (this repo is tested locally with the system Python available in this workspace)

Python deps for the API server are listed in `requirements.txt`:

```bash
python3 -m pip install -r requirements.txt
```

## Optional: PDF/OCR Support

Receipt/bill parsing works with `*.txt` inputs out of the box.

For PDF text extraction install one of:

- `pdfplumber` (preferred)
- `pypdf`

For image OCR install:

- `pytesseract` (Python wrapper)
- plus the system `tesseract` binary available on your machine

Quick check:

```bash
python3 -m ledgerflow ocr doctor
```

## Run Tests

```bash
python3 -m unittest discover -s tests
```

## Run CLI

```bash
python3 -m ledgerflow --help
```

## Run Server

```bash
python3 -m ledgerflow serve --host 127.0.0.1 --port 8787
```
