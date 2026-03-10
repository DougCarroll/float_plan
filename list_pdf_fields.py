#!/usr/bin/env python3
"""Print AcroForm field names from USCGFloatPlan.pdf. Use after changing template."""
from pathlib import Path

from pypdf import PdfReader

PDF = Path(__file__).resolve().parent / "USCGFloatPlan.pdf"

def main():
    if not PDF.exists():
        print(f"Not found: {PDF}")
        return
    r = PdfReader(PDF)
    fields = r.get_fields()
    if not fields:
        print("No form fields in this PDF.")
        print("Pages:", len(r.pages))
        return
    for name in sorted(fields.keys()):
        print(name)
    print(f"\nTotal: {len(fields)} fields, {len(r.pages)} page(s)")

if __name__ == "__main__":
    main()
