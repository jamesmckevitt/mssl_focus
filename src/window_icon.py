from pathlib import Path
import sys
import tkinter as tk


def _resource_path(filename):
    if getattr(sys, "frozen", False):
        base_dir = Path(sys._MEIPASS)
    else:
        base_dir = Path(__file__).resolve().parent.parent
    return base_dir / filename


def set_app_icon(window):
    """Apply the bundled application icon to a Tk or Toplevel window."""
    ico_path = _resource_path("app.ico")
    png_path = _resource_path("app.png")

    if sys.platform == "win32" and ico_path.is_file():
        icon_applied = False
        try:
            window.iconbitmap(str(ico_path))
            icon_applied = True
        except tk.TclError:
            pass
        try:
            window.iconbitmap(default=str(ico_path))
            icon_applied = True
        except tk.TclError:
            pass

        if icon_applied:
            def reapply_icon():
                try:
                    window.iconbitmap(str(ico_path))
                    window.iconbitmap(default=str(ico_path))
                except tk.TclError:
                    pass

            try:
                window.after_idle(reapply_icon)
            except tk.TclError:
                pass
            return True

    try:
        from PIL import Image, ImageDraw, ImageTk

        if png_path.is_file():
            with Image.open(png_path) as image:
                photo = ImageTk.PhotoImage(image.copy())
        else:
            size = 64
            margin = 5
            image = Image.new("RGBA", (size, size), (255, 255, 255, 255))
            draw = ImageDraw.Draw(image)
            x0 = y0 = margin
            x1 = y1 = size - margin - 1
            draw.rectangle(
                [x0, y0, x1, y1], fill="white", outline="black", width=2
            )
            for fraction in (1 / 3, 2 / 3):
                x = round(x0 + fraction * (x1 - x0))
                y = round(y0 + fraction * (y1 - y0))
                draw.line([(x, y0), (x, y1)], fill="black", width=2)
                draw.line([(x0, y), (x1, y)], fill="black", width=2)
            photo = ImageTk.PhotoImage(image)

        window.iconphoto(True, photo)
        window._app_icon_photo = photo
        return True
    except (ImportError, OSError, tk.TclError):
        return False


__all__ = ["set_app_icon"]
