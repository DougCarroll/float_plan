#!/usr/bin/env python3
"""Standalone file picker for .floatplan files. Writes selected path to --output file and exits.
Used as a subprocess by the main app to avoid macOS Tk/Cocoa crash when opening a plan."""
import argparse
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk


def main():
    parser = argparse.ArgumentParser(description="Pick a .floatplan or .json file")
    parser.add_argument("--output", required=True, help="Write selected path to this file")
    parser.add_argument("start_dir", nargs="?", default=None, help="Starting directory")
    args = parser.parse_args()
    start_dir = Path(args.start_dir).resolve() if args.start_dir else Path.home()
    if not start_dir.is_dir():
        start_dir = Path.home()
    output_path = Path(args.output)
    current = [start_dir]
    result = [None]

    root = tk.Tk()
    root.title("Open plan")
    root.geometry("500x380")
    # Bring picker to front without -topmost (can trigger macOS Cocoa crash). Lift once now and again after map.
    root.lift()
    root.after(150, root.lift)
    f = ttk.Frame(root, padding=10)
    f.pack(fill=tk.BOTH, expand=True)
    ttk.Label(f, text="Current folder:").grid(row=0, column=0, sticky=tk.W)
    dir_label = ttk.Label(f, text=str(current[0]), wraplength=400)
    dir_label.grid(row=0, column=1, sticky=tk.EW, padx=(8, 0))
    ttk.Label(f, text="Double-click a file to open, or folder to go in.").grid(
        row=1, column=0, columnspan=2, sticky=tk.W, pady=(0, 4)
    )
    list_f = ttk.Frame(f)
    list_f.grid(row=2, column=0, columnspan=2, sticky=tk.NSEW, pady=4)
    lb = tk.Listbox(list_f, height=14, width=55)
    lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    sb = ttk.Scrollbar(list_f, orient=tk.VERTICAL, command=lb.yview)
    sb.pack(side=tk.RIGHT, fill=tk.Y)
    lb.configure(yscrollcommand=sb.set)
    root.columnconfigure(0, weight=1)
    f.columnconfigure(1, weight=1)
    f.rowconfigure(2, weight=1)

    def refresh():
        lb.delete(0, tk.END)
        p = current[0]
        dir_label.config(text=str(p))
        try:
            entries = []
            for e in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                if e.is_dir() and not e.name.startswith("."):
                    entries.append((e.name + "/", e, True))
                elif e.is_file() and e.suffix.lower() in (".floatplan", ".json"):
                    entries.append((e.name, e, False))
            for name, entry, is_dir in entries:
                lb.insert(tk.END, name)
                lb.itemconfig(lb.size() - 1, {"fg": "blue" if is_dir else "black"})
            if p.parent != p:
                lb.insert(0, ".. (parent folder)")
                lb.itemconfig(0, fg="gray")
        except PermissionError:
            lb.insert(tk.END, "(No permission to list folder)")
        except OSError as err:
            lb.insert(tk.END, f"(Error: {err})")

    def select_file(path_str: str) -> None:
        result[0] = path_str
        root.quit()
        root.destroy()

    def on_double_click(ev):
        sel = lb.curselection()
        if not sel:
            return
        idx = int(sel[0])
        p = current[0]
        try:
            if p.parent != p and idx == 0:
                current[0] = p.parent
                refresh()
                return
            entries = []
            for e in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                if e.is_dir() and not e.name.startswith("."):
                    entries.append((e.name + "/", e, True))
                elif e.is_file() and e.suffix.lower() in (".floatplan", ".json"):
                    entries.append((e.name, e, False))
            if p.parent != p:
                entries.insert(0, ("..", p.parent, True))
            name, entry, is_dir = entries[idx]
            if is_dir:
                current[0] = entry
                refresh()
            else:
                select_file(str(entry))
        except (IndexError, PermissionError, OSError):
            pass

    def show_alert(title: str, message: str) -> None:
        """Show a modal message without messagebox (avoids macOS NSAlert autorelease crash)."""
        top = tk.Toplevel(root)
        top.title(title)
        top.transient(root)
        top.grab_set()
        f = ttk.Frame(top, padding=15)
        f.pack(fill=tk.BOTH, expand=True)
        ttk.Label(f, text=message, wraplength=350).pack(pady=(0, 12))
        ttk.Button(f, text="OK", command=top.destroy).pack()
        top.protocol("WM_DELETE_WINDOW", top.destroy)
        top.wait_window()

    def on_open():
        sel = lb.curselection()
        if not sel:
            show_alert("Open plan", "Select a file first.")
            return
        on_double_click(None)

    def on_cancel():
        root.quit()
        root.destroy()

    lb.bind("<Double-Button-1>", on_double_click)
    refresh()
    btn_f = ttk.Frame(f)
    btn_f.grid(row=3, column=0, columnspan=2, pady=(8, 0))
    ttk.Button(btn_f, text="Open", command=on_open).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(btn_f, text="Cancel", command=on_cancel).pack(side=tk.LEFT)
    root.protocol("WM_DELETE_WINDOW", on_cancel)
    root.mainloop()
    if result[0]:
        try:
            output_path.write_text(result[0], encoding="utf-8")
        except OSError:
            pass
    sys.exit(0)


if __name__ == "__main__":
    main()
