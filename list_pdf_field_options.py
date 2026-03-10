#!/usr/bin/env python3
"""Print dropdown/choice options for each form field in USCGFloatPlan.pdf.
To change options: edit dropdown_options.json in this folder, then restart the app."""
from pathlib import Path

from pdf_form_options import get_options_from_pdf, FORM_OPTIONS, OPTIONS_FILE

def main():
    print("Edit dropdown options in:", OPTIONS_FILE)
    print()
    pdf = Path(__file__).resolve().parent / "USCGFloatPlan.pdf"
    from_pdf = get_options_from_pdf(pdf)
    if from_pdf:
        print("Options read from PDF:")
        for name in sorted(from_pdf.keys()):
            print(f"  {name}: {from_pdf[name]}")
    else:
        print("Could not read options from PDF (encrypted or no choice fields).")
    print("\nCurrent FORM_OPTIONS fallbacks (used when PDF not read):")
    for k in sorted(FORM_OPTIONS.keys()):
        if not k.startswith("0") or k == "01DepartMode":
            print(f"  {k}: {FORM_OPTIONS[k]}")

if __name__ == "__main__":
    main()
