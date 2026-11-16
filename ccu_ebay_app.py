"""
CCU eBay Requested Fields: the requested-fields CSV as one program (READ-ONLY: never edits eBay or Shopify)

Double-click the program (CCU eBay Reports.exe on Windows, "CCU eBay Reports" on a Mac). It asks which eBay
account (when config.yaml has more than one), builds the requested-fields CSV and opens it.

config.yaml is NOT built into the program. At the start it shows which config.yaml it will use (the last one
chosen, else one next to the program / in Downloads / Documents); press Enter to use it, or C to choose another.
The choice is remembered in ccu_ebay_settings.json next to the program (only the file's location, never its contents).
The CSV is saved in a "ccu_report_output" folder next to the program.

Build:  "Build Windows eBay App.bat" (on Windows)  /  "Build Mac eBay App.command" (on a Mac)
Run from source:  python ccu_ebay_app.py
"""
import json, os, sys, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ccu_ebay_report as core          # noqa: E402
import requested_fields_report as rf    # noqa: E402

APP_VERSION = "2026-11-12c"
SETTINGS = os.path.join(core.HERE, "ccu_ebay_settings.json")


def remembered_config():
    try:
        p = json.load(open(SETTINGS, encoding="utf-8")).get("config", "")
        return p if core.has_ebay_section(p) else None
    except (OSError, ValueError, AttributeError):
        return None


def remember_config(path):
    try:
        json.dump({"config": path}, open(SETTINGS, "w", encoding="utf-8"))
    except OSError:
        pass


def pick_file():
    """File picker window; None if cancelled or no window toolkit (then the path is typed instead)."""
    try:
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        p = filedialog.askopenfilename(title="Choose config.yaml", initialdir=os.path.expanduser("~"),
                                       filetypes=[("YAML", "*.yaml *.yml"), ("All files", "*.*")])
        root.destroy()
        return p or None
    except Exception:
        typed = input("Type (or drag in) the full path of config.yaml, then press Enter:\n> ").strip()
        return typed.strip('"').strip("'").replace("\\ ", " ") or None


def choose_config():
    current = remembered_config() or core.find_config(required=False)
    while True:
        if current:
            print(f"config.yaml: {current}")
            a = input("Press Enter to use it, or type C and press Enter to choose a different one: ").strip().lower()
            if a == "":
                return current
            if a != "c":
                continue
        else:
            print("No config.yaml with an eBay section was found. Choose one.")
        p = pick_file()
        if not p:
            if not current:
                sys.exit("No config.yaml chosen.")
            continue
        p = os.path.abspath(os.path.expanduser(p))
        if not core.has_ebay_section(p):
            print(f"  {p} is not a config.yaml with an 'ebay:' section. Choose another one.\n")
            continue
        remember_config(p)
        current = p
        print()


def main():
    print(f"CCU eBay Requested Fields  (version {APP_VERSION}, read-only: changes nothing on eBay or Shopify)\n")
    try:
        args = sys.argv[1:]
        if "--config" not in args:
            args += ["--config", choose_config()]
        result = rf.main(args)
        if result and os.path.exists(result):
            print("\nOpening the CSV...")
            core.open_file(result)
        print("\nDone.")
    except KeyboardInterrupt:
        print("\nStopped.")
    except EOFError:
        return
    except SystemExit as e:              # the report stops with a plain-English message
        if e.code not in (None, 0):
            print(f"\n{e.code}" if isinstance(e.code, str) else f"\nStopped (code {e.code}).")
    except Exception:
        print("\nSomething went wrong. Copy the text below (never a token or password) and send it to the person who set up the app:\n")
        traceback.print_exc()
    try:
        input("\nPress Enter to close this window.")
    except EOFError:
        pass


if __name__ == "__main__":
    main()
