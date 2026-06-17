"""Dump raw pdfplumber text extraction for a Betterment statement PDF.

Redacts dollar amounts and account numbers before printing.

Usage:
    python scripts/debug_pdf.py path/to/statement.pdf
"""
import re
import sys
import pdfplumber

path = sys.argv[1] if len(sys.argv) > 1 else None
if not path:
    print("Usage: python scripts/debug_pdf.py path/to/statement.pdf")
    sys.exit(1)

def redact(line: str) -> str:
    # Dollar amounts: $1,234.56 or $1234.56
    line = re.sub(r'\$[\d,]+\.?\d*', '$[AMOUNT]', line)
    # Standalone numbers that look like account numbers (8+ digits)
    line = re.sub(r'\b\d{8,}\b', '[ACCT#]', line)
    # Remaining standalone numbers (balances without $ sign, share counts, etc.)
    line = re.sub(r'\b\d[\d,.]*\d\b', '[NUM]', line)
    return line

with pdfplumber.open(path) as pdf:
    for i, page in enumerate(pdf.pages):
        print(f"\n{'='*60}")
        print(f"PAGE {i+1}")
        print('='*60)
        text = page.extract_text() or ""
        for lineno, line in enumerate(text.splitlines(), 1):
            print(f"{lineno:4d} | {repr(redact(line))}")
