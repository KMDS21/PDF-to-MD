"""PDF-to-MD Converter — entry point.

Launches the desktop GUI. Falls back to a console message if the GUI
is not yet available (earlier milestones).
"""

APP_NAME = "PDF-to-MD Converter"


def main() -> None:
    try:
        from app.gui import main as gui_main
    except ImportError:
        print(f"{APP_NAME}")
        print("The GUI is not available yet — still under construction.")
        print("Run `python -m app.converter <input_folder> <output_folder>` for CLI use.")
        return
    gui_main()


if __name__ == "__main__":
    main()
