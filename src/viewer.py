import math
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk

import numpy as np
from PIL import Image, ImageFilter, ImageTk

from .constants import BACKLIT_IMAGE_LABEL, FRONTLIT_IMAGE_LABEL

_RAW_EXTENSIONS = {'.arw', '.nef', '.cr2', '.cr3', '.orf', '.rw2', '.dng', '.raf', '.pef', '.srw'}


def _open_image(path):
    """Open a standard or camera RAW image and return a PIL Image."""
    if os.path.splitext(path)[1].lower() in _RAW_EXTENSIONS:
        import rawpy
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess(use_camera_wb=True)
        return Image.fromarray(rgb)
    return Image.open(path)


def _denoise_gray_nlm(cv2, gray, amount, aggressive):
    frac = max(0.0, min(1.0, float(amount) / 100.0))
    h = frac * (34.0 if aggressive else 24.0)
    search = 21 if aggressive else (17 if frac >= 0.6 else 13)
    denoised = cv2.fastNlMeansDenoising(gray, None, h, 7, search)
    if aggressive and frac >= 0.65:
        second_h = max(6.0, h * 0.8)
        denoised = cv2.fastNlMeansDenoising(denoised, None, second_h, 7, 21)
    return denoised


def _edge_blend_gray(cv2, original_gray, denoised_gray, edge_amount):
    edge_frac = max(0.0, min(1.0, float(edge_amount) / 100.0))
    original = original_gray.astype(np.float32)
    denoised = denoised_gray.astype(np.float32)
    gx = cv2.Sobel(original, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(original, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    scale = float(np.percentile(mag, 95)) if mag.size else 0.0
    edge_mask = np.clip(mag / max(scale, 1e-6), 0.0, 1.0)
    denoise_weight = 1.0 - edge_mask * (1.0 - edge_frac)
    blended = original * (1.0 - denoise_weight) + denoised * denoise_weight
    return np.clip(blended, 0, 255).astype(np.uint8)


def _denoise_color_nlm(cv2, rgb, amount, color_amount, edge_amount, aggressive):
    frac = max(0.0, min(1.0, float(amount) / 100.0))
    color_frac = max(0.0, min(1.0, float(color_amount) / 100.0))
    h = frac * (34.0 if aggressive else 24.0)
    h_color = h * 1.6 * color_frac
    search = 21 if aggressive else (17 if frac >= 0.6 else 13)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    denoised = cv2.fastNlMeansDenoisingColored(bgr, None, h, h_color, 7, search)
    if aggressive and frac >= 0.65:
        second_h = max(6.0, h * 0.8)
        denoised = cv2.fastNlMeansDenoisingColored(
            denoised, None, second_h, second_h * 1.6 * color_frac, 7, 21
        )
    denoised_rgb = cv2.cvtColor(denoised, cv2.COLOR_BGR2RGB)
    original_ycc = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
    denoised_ycc = cv2.cvtColor(denoised_rgb, cv2.COLOR_RGB2YCrCb)
    denoised_ycc[:, :, 0] = _edge_blend_gray(
        cv2,
        original_ycc[:, :, 0],
        denoised_ycc[:, :, 0],
        edge_amount,
    )
    return cv2.cvtColor(denoised_ycc, cv2.COLOR_YCrCb2RGB)

class ViewerMixin:
    def _iter_all_canvases(self):
        return (self.canvas1, self.canvas2, self.canvas3, self.canvas4)

    def _iter_visible_canvases(self):
        canvases = [self.canvas1]
        if self.mode_var.get() != "overlay":
            canvases.append(self.canvas2)
        if self.show_compare_row_var.get():
            canvases.append(self.canvas3)
            if self.mode_var.get() != "overlay":
                canvases.append(self.canvas4)
        return tuple(canvases)

    def _image_label(self, idx, row="top"):
        base = BACKLIT_IMAGE_LABEL if idx == 0 else FRONTLIT_IMAGE_LABEL
        if row == "compare":
            return f"{base} (Bottom Row)"
        return base

    def _is_compare_canvas(self, widget):
        return widget in (self.canvas3, self.canvas4)

    def _get_image_state(self, row="top"):
        if row == "compare":
            return {
                "images": self.compare_row_images,
                "image_paths": self.compare_row_image_paths,
                "preview_images": self.compare_row_preview_images,
                "preview_scales": self.compare_row_preview_scales,
                "photos": self.compare_row_photos,
                "base_images": self._compare_row_base_images,
                "rotated_cache": self._compare_row_rotated_cache,
                "last_rot": self._compare_row_last_rot,
                "rotated_preview_cache": self._compare_row_rotated_preview_cache,
                "last_rot_preview": self._compare_row_last_rot_preview,
                "adj_vars": self.compare_row_adj_vars,
            }
        return {
            "images": self.images,
            "image_paths": self.image_paths,
            "preview_images": self.preview_images,
            "preview_scales": self.preview_scales,
            "photos": self.photos,
            "base_images": self._base_images,
            "rotated_cache": self._rotated_cache,
            "last_rot": self._last_rot,
            "rotated_preview_cache": self._rotated_preview_cache,
            "last_rot_preview": self._last_rot_preview,
            "adj_vars": self.adj_vars,
        }

    def _get_noise_reduction_state(self, row="top"):
        if row == "compare":
            return {
                "amount_vars": self.compare_row_nr_amount_vars,
                "aggressive_vars": self.compare_row_nr_aggressive_vars,
                "color_vars": self.compare_row_nr_color_vars,
                "edge_vars": self.compare_row_nr_edge_vars,
            }
        return {
            "amount_vars": self.nr_amount_vars,
            "aggressive_vars": self.nr_aggressive_vars,
            "color_vars": self.nr_color_vars,
            "edge_vars": self.nr_edge_vars,
        }

    def _show_noise_reduction_progress(self, idx, amount, color_amount, edge_amount, aggressive):
        existing = getattr(self, "_nr_progress_dialog", None)
        if existing is not None:
            win = existing.get("window")
            if win is not None and win.winfo_exists():
                try:
                    existing["bar"].stop()
                    win.grab_release()
                except Exception:
                    pass
                win.destroy()

        win = tk.Toplevel(self.root)
        win.title("Applying noise reduction")
        win.configure(bg="#2b2b2b")
        win.resizable(False, False)
        win.transient(self.root)
        win.protocol("WM_DELETE_WINDOW", lambda: None)

        tk.Label(
            win,
            text=(
                f"Image {idx + 1}: applying {'aggressive ' if aggressive else ''}noise reduction\n"
                f"NR {amount}  |  Color {color_amount}  |  Edge {edge_amount}"
            ),
            bg="#2b2b2b",
            fg="#ddd",
            justify=tk.LEFT,
            font=("TkDefaultFont", 9),
            padx=16,
            pady=12,
        ).pack(fill=tk.X)

        bar = ttk.Progressbar(win, mode="indeterminate", length=320)
        bar.pack(padx=16, pady=(0, 14))
        bar.start(10)

        win.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - win.winfo_width()) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - win.winfo_height()) // 2)
        win.geometry(f"+{x}+{y}")
        win.grab_set()
        self._nr_progress_dialog = {"window": win, "bar": bar}

    def _close_noise_reduction_progress(self):
        existing = getattr(self, "_nr_progress_dialog", None)
        self._nr_progress_dialog = None
        if existing is None:
            return
        win = existing.get("window")
        if win is None or not win.winfo_exists():
            return
        try:
            existing["bar"].stop()
        except Exception:
            pass
        try:
            win.grab_release()
        except Exception:
            pass
        win.destroy()

    def load_image(self, idx, row="top"):
        state = self._get_image_state(row)
        path = filedialog.askopenfilename(
            title=f"Open {self._image_label(idx, row)}",
            filetypes=[
                ("Image files",
                 "*.tif *.tiff *.TIF *.TIFF "
                 "*.png *.PNG "
                 "*.jpg *.JPG *.jpeg *.JPEG "
                 "*.bmp *.BMP *.webp *.WEBP "
                 "*.arw *.ARW *.nef *.NEF *.cr2 *.CR2 *.cr3 *.CR3 "
                 "*.dng *.DNG *.orf *.ORF *.rw2 *.RW2 *.raf *.RAF"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        img = _open_image(path)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        state["images"][idx] = img
        state["base_images"][idx] = img
        state["image_paths"][idx] = path
        state["preview_images"][idx], state["preview_scales"][idx] = self._make_preview(img)
        state["rotated_cache"][idx] = None
        state["last_rot"][idx] = None
        state["rotated_preview_cache"][idx] = None
        state["last_rot_preview"][idx] = None
        if row == "compare":
            self.show_compare_row_var.set(True)
            self._on_compare_row_toggle()
        self.status_var.set(f"{self._image_label(idx, row)} loaded: {path}  ({img.width}x{img.height})")
        self._schedule_render()

    def _apply_noise_reduction(self, idx, row="top", on_complete=None):
        """Apply NLM noise reduction (OpenCV, CIELAB space) in a background thread."""
        image_state = self._get_image_state(row)
        nr_state = self._get_noise_reduction_state(row)
        base = image_state["base_images"][idx]
        image_label = self._image_label(idx, row)
        if base is None:
            self.status_var.set(f"{image_label}: no image loaded")
            if on_complete is not None:
                on_complete(False)
            return
        amount = nr_state["amount_vars"][idx].get()
        color_amount = nr_state["color_vars"][idx].get()
        edge_amount = nr_state["edge_vars"][idx].get()
        aggressive = bool(nr_state["aggressive_vars"][idx].get())

        if amount == 0:
            img = base.copy()
            image_state["images"][idx] = img
            image_state["preview_images"][idx], image_state["preview_scales"][idx] = self._make_preview(img)
            image_state["rotated_cache"][idx] = None
            image_state["last_rot"][idx] = None
            image_state["rotated_preview_cache"][idx] = None
            image_state["last_rot_preview"][idx] = None
            self.status_var.set(f"{image_label}: noise reduction cleared")
            self._schedule_render()
            if on_complete is not None:
                on_complete(True)
            return

        self.status_var.set(
            f"{image_label}: applying {'aggressive ' if aggressive else ''}NR "
            f"(amount {amount}, color {color_amount}, edge {edge_amount}) -- please wait..."
        )
        self.root.update_idletasks()
        self._show_noise_reduction_progress(idx, amount, color_amount, edge_amount, aggressive)

        result_q = queue.SimpleQueue()

        def _worker():
            try:
                import cv2
                if base.mode == "L":
                    gray = np.array(base.convert("L"))
                    denoised = _denoise_gray_nlm(cv2, gray, amount, aggressive)
                    denoised = _edge_blend_gray(cv2, gray, denoised, edge_amount)
                    img = Image.fromarray(denoised)
                else:
                    rgb = np.array(base.convert("RGB"))
                    denoised = _denoise_color_nlm(
                        cv2, rgb, amount, color_amount, edge_amount, aggressive
                    )
                    img = Image.fromarray(denoised)
                result_q.put(("ok", img))
            except ImportError:
                # Fallback: YCbCr Gaussian blur
                edge_frac = max(0.0, min(1.0, float(edge_amount) / 100.0))
                color_frac = max(0.0, min(1.0, float(color_amount) / 100.0))
                luma_r = amount / 100.0 * (2.0 + edge_frac * (3.0 if aggressive else 2.0))
                chroma_r = amount / 100.0 * ((3.0 if aggressive else 2.0) + color_frac * (9.0 if aggressive else 6.0))
                try:
                    if base.mode == "L":
                        img = base.filter(ImageFilter.GaussianBlur(radius=luma_r))
                        if aggressive and amount >= 65:
                            img = img.filter(ImageFilter.GaussianBlur(radius=max(1.0, luma_r * 0.8)))
                    else:
                        y, cb, cr = base.convert("YCbCr").split()
                        y  = y.filter(ImageFilter.GaussianBlur(radius=luma_r))
                        cb = cb.filter(ImageFilter.GaussianBlur(radius=chroma_r))
                        cr = cr.filter(ImageFilter.GaussianBlur(radius=chroma_r))
                        if aggressive and amount >= 65:
                            y = y.filter(ImageFilter.GaussianBlur(radius=max(1.0, luma_r * 0.8)))
                            cb = cb.filter(ImageFilter.GaussianBlur(radius=max(1.5, chroma_r * 0.8)))
                            cr = cr.filter(ImageFilter.GaussianBlur(radius=max(1.5, chroma_r * 0.8)))
                        img = Image.merge("YCbCr", (y, cb, cr)).convert("RGB")
                    result_q.put(("ok", img))
                except Exception as e:
                    result_q.put(("error", str(e)))
            except Exception as e:
                result_q.put(("error", str(e)))

        def _poll():
            try:
                status, value = result_q.get_nowait()
            except queue.Empty:
                self.root.after(50, _poll)
                return
            self._close_noise_reduction_progress()
            if status == "error":
                self.status_var.set(f"{image_label}: NR failed -- {value}")
                if on_complete is not None:
                    on_complete(False)
                return
            img = value
            image_state["images"][idx] = img
            image_state["preview_images"][idx], image_state["preview_scales"][idx] = self._make_preview(img)
            image_state["rotated_cache"][idx] = None
            image_state["last_rot"][idx] = None
            image_state["rotated_preview_cache"][idx] = None
            image_state["last_rot_preview"][idx] = None
            self.status_var.set(
                f"{image_label}: {'aggressive ' if aggressive else ''}noise reduction applied "
                f"(amount {amount}, color {color_amount}, edge {edge_amount})"
            )
            self._schedule_render()
            if on_complete is not None:
                on_complete(True)

        threading.Thread(target=_worker, daemon=True).start()
        self.root.after(50, _poll)

    def _on_mode_change(self):
        if self.mode_var.get() == "overlay":
            self.canvas2.pack_forget()
            self.canvas4.pack_forget()
        else:
            self.canvas2.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            if self.show_compare_row_var.get():
                self.canvas4.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        if self.show_compare_row_var.get():
            self.compare_canvas_row.pack(fill=tk.BOTH, expand=True)
        else:
            self.compare_canvas_row.pack_forget()
        self._schedule_render()

    def _on_alignment_change(self):
        self._schedule_render()

    def _on_opacity(self, val):
        self.opacity = float(val)
        self._schedule_render()

    def _reset_alignment(self):
        self.off_x_var.set("0")
        self.off_y_var.set("0")
        self.rot_var.set("0.0")
        self.img2_scale_var.set("1.000")
        self.glob_rot_var.set("0.0")
        self._schedule_render()

    def _nudge_global(self, dr):
        try:
            r = float(self.glob_rot_var.get()) + dr
            self.glob_rot_var.set(f"{r:.1f}")
        except ValueError:
            pass
        self._schedule_render()

    def _nudge(self, dx, dy, dr):
        try:
            x = float(self.off_x_var.get()) + dx
            y = float(self.off_y_var.get()) + dy
            r = float(self.rot_var.get()) + dr
            self.off_x_var.set(str(int(x)))
            self.off_y_var.set(str(int(y)))
            self.rot_var.set(f"{r:.1f}")
        except ValueError:
            pass
        self._schedule_render()

    def _on_pan_start(self, event):
        self._interacting = True
        self.last_pan = (event.x, event.y)

    def _on_pan(self, event):
        dx = event.x - self.last_pan[0]
        dy = event.y - self.last_pan[1]
        self.pan_x += dx
        self.pan_y += dy
        self.last_pan = (event.x, event.y)
        for canvas in self._iter_visible_canvases():
            canvas.move("img", dx, dy)
        self.canvas1.move("annotations", dx, dy)
        self.canvas2.move("annotations", dx, dy)
        self._draw_cursors()
        self._schedule_render()
        self._schedule_quality_render()

    def _on_zoom(self, event):
        if hasattr(event, "delta") and event.delta:
            factor = 1.0015 ** event.delta
        elif getattr(event, "num", None) == 4:
            factor = 1.12
        else:
            factor = 1 / 1.12
        factor = max(0.5, min(2.0, factor))
        cx, cy = event.x, event.y
        self.pan_x = cx - (cx - self.pan_x) * factor
        self.pan_y = cy - (cy - self.pan_y) * factor
        self.zoom *= factor
        self.zoom = max(0.02, min(100.0, self.zoom))
        self._interacting = True
        self._schedule_render()
        self._schedule_quality_render()

    def _on_mouse_move(self, event):
        self.cursor_pos = (event.x, event.y)
        if event.widget is self.canvas2:
            img_x, img_y = self._canvas_to_img2(event.x, event.y)
            off_x, off_y, rot, _glob_rot = self._get_alignment_values()
            scale = self._get_img2_scale()
            row_name = FRONTLIT_IMAGE_LABEL
        elif event.widget is self.canvas3:
            img_x, img_y = self._canvas_to_compare_img1(event.x, event.y)
            off_x, off_y, rot, _glob_rot = self._get_compare_row_alignment_values()
            scale = self._get_compare_row_img2_scale()
            row_name = f"{BACKLIT_IMAGE_LABEL} (Bottom Row)"
        elif event.widget is self.canvas4:
            img_x, img_y = self._canvas_to_compare_img2(event.x, event.y)
            off_x, off_y, rot, _glob_rot = self._get_compare_row_alignment_values()
            scale = self._get_compare_row_img2_scale()
            row_name = f"{FRONTLIT_IMAGE_LABEL} (Bottom Row)"
        else:
            img_x, img_y = self._canvas_to_img1(event.x, event.y)
            off_x, off_y, rot, _glob_rot = self._get_alignment_values()
            scale = self._get_img2_scale()
            row_name = BACKLIT_IMAGE_LABEL
        self.status_var.set(
            f"{row_name} coords: ({img_x:.1f}, {img_y:.1f})  |  "
            f"Zoom: {self.zoom:.2f}x  |  "
            f"Offset: ({off_x}, {off_y})  |  "
            f"Rotation: {rot:.2f}deg  |  "
            f"Scale: {scale:.3f}x"
        )
        self._draw_cursors()
        if self.align_mode_var.get() or self.align_scale_mode_var.get():
            if event.widget is self.canvas2:
                self._align_guide_cursor = (event.x, event.y)
            else:
                self._align_guide_cursor = None
            self._draw_align_guide()
        if self.compare_row_align_mode_var.get() or self.compare_row_align_scale_mode_var.get():
            if event.widget is self.canvas4:
                self._compare_row_align_guide_cursor = (event.x, event.y)
            else:
                self._compare_row_align_guide_cursor = None
            self._draw_compare_row_align_guide()
        if self.crop_mode_var.get() and self._crop_corner1 is not None:
            self._draw_crop_preview(event.x, event.y)

    def _schedule_quality_render(self):
        if self._quality_timer is not None:
            self.root.after_cancel(self._quality_timer)
        self._quality_timer = self.root.after(150, self._on_interaction_end)

    def _on_interaction_end(self):
        self._quality_timer = None
        self._interacting = False
        self._render()

    def _make_preview(self, img, max_dim=2200):
        largest = max(img.width, img.height)
        if largest <= max_dim:
            return img, 1.0
        scale = max_dim / float(largest)
        w = max(1, int(round(img.width * scale)))
        h = max(1, int(round(img.height * scale)))
        return img.resize((w, h), resample=Image.BILINEAR), scale

    def _schedule_render(self):
        if not self._render_pending:
            self._render_pending = True
            self.root.after(16, self._render)

    def _render(self):
        self._render_pending = False
        mode = self.mode_var.get()
        try:
            off_x = int(float(self.off_x_var.get()))
            off_y = int(float(self.off_y_var.get()))
            rot = float(self.rot_var.get())
            glob_rot = float(self.glob_rot_var.get())
            img2_scale = self._get_img2_scale()
        except ValueError:
            off_x, off_y, rot, glob_rot, img2_scale = 0, 0, 0.0, 0.0, 1.0

        w1 = max(self.canvas1.winfo_width(), 1)
        h1 = max(self.canvas1.winfo_height(), 1)

        if mode == "overlay":
            v1 = self._get_view(self.images[0], 0, 0, glob_rot, w1, h1, idx=0)
            v2 = self._get_view(self.images[1], off_x, off_y, glob_rot + rot, w1, h1,
                                idx=1, align_scale=img2_scale)
            alpha = self.opacity_var.get()
            if self.images[0] and self.images[1]:
                blended = Image.blend(v1.convert("RGB"), v2.convert("RGB"), alpha)
            elif self.images[0]:
                blended = v1
            else:
                blended = v2
            self.photos[0] = ImageTk.PhotoImage(blended)
            if self.canvas1.find_withtag("img"):
                self.canvas1.itemconfig("img", image=self.photos[0])
                self.canvas1.coords("img", 0, 0)
            else:
                self.canvas1.create_image(0, 0, anchor=tk.NW,
                                          image=self.photos[0], tags="img")
            self.canvas1.tag_raise("badge1")
        else:
            w2 = max(self.canvas2.winfo_width(), 1)
            h2 = max(self.canvas2.winfo_height(), 1)

            v1 = self._get_view(self.images[0], 0, 0, glob_rot, w1, h1, idx=0)
            v2 = self._get_view(self.images[1], off_x, off_y, glob_rot + rot, w2, h2,
                                idx=1, align_scale=img2_scale)

            self.photos[0] = ImageTk.PhotoImage(v1)
            self.photos[1] = ImageTk.PhotoImage(v2)

            if self.canvas1.find_withtag("img"):
                self.canvas1.itemconfig("img", image=self.photos[0])
                self.canvas1.coords("img", 0, 0)
            else:
                self.canvas1.create_image(0, 0, anchor=tk.NW,
                                          image=self.photos[0], tags="img")

            if self.canvas2.find_withtag("img"):
                self.canvas2.itemconfig("img", image=self.photos[1])
                self.canvas2.coords("img", 0, 0)
            else:
                self.canvas2.create_image(0, 0, anchor=tk.NW,
                                          image=self.photos[1], tags="img")
            self.canvas1.tag_raise("badge1")
            self.canvas2.tag_raise("badge2")

        self._render_compare_row()

        self._draw_annotations()
        self._draw_align_pts()
        self._draw_cursors()

    def _render_compare_row(self):
        if not self.show_compare_row_var.get():
            return

        try:
            off_x = int(float(self.compare_row_off_x_var.get()))
            off_y = int(float(self.compare_row_off_y_var.get()))
            rot = float(self.compare_row_rot_var.get())
            glob_rot = float(self.compare_row_glob_rot_var.get())
            img2_scale = max(0.1, float(self.compare_row_img2_scale_var.get()))
            row_shift_x = int(float(self.compare_row_shift_x_var.get()))
            row_shift_y = int(float(self.compare_row_shift_y_var.get()))
            row_shift_rot = float(self.compare_row_shift_rot_var.get())
            row_shift_scale = max(0.1, float(self.compare_row_shift_scale_var.get()))
        except ValueError:
            off_x = off_y = row_shift_x = row_shift_y = 0
            rot = glob_rot = row_shift_rot = 0.0
            img2_scale = row_shift_scale = 1.0

        state = self._get_image_state("compare")
        w3 = max(self.canvas3.winfo_width(), 1)
        h3 = max(self.canvas3.winfo_height(), 1)

        if self.mode_var.get() == "overlay":
            v3 = self._get_view(
                state["images"][0],
                row_shift_x,
                row_shift_y,
                glob_rot + row_shift_rot,
                w3,
                h3,
                idx=0,
                align_scale=row_shift_scale,
                preview_images=state["preview_images"],
                preview_scales=state["preview_scales"],
                rotated_cache=state["rotated_cache"],
                last_rot=state["last_rot"],
                rotated_preview_cache=state["rotated_preview_cache"],
                last_rot_preview=state["last_rot_preview"],
                adj_vars=state["adj_vars"],
            )
            v4 = self._get_view(
                state["images"][1],
                row_shift_x + int(round(off_x * row_shift_scale)),
                row_shift_y + int(round(off_y * row_shift_scale)),
                glob_rot + row_shift_rot + rot,
                w3,
                h3,
                idx=1,
                align_scale=row_shift_scale * img2_scale,
                preview_images=state["preview_images"],
                preview_scales=state["preview_scales"],
                rotated_cache=state["rotated_cache"],
                last_rot=state["last_rot"],
                rotated_preview_cache=state["rotated_preview_cache"],
                last_rot_preview=state["last_rot_preview"],
                adj_vars=state["adj_vars"],
            )
            alpha = self.opacity_var.get()
            if state["images"][0] and state["images"][1]:
                blended = Image.blend(v3.convert("RGB"), v4.convert("RGB"), alpha)
            elif state["images"][0]:
                blended = v3
            else:
                blended = v4
            state["photos"][0] = ImageTk.PhotoImage(blended)
            if self.canvas3.find_withtag("img"):
                self.canvas3.itemconfig("img", image=state["photos"][0])
                self.canvas3.coords("img", 0, 0)
            else:
                self.canvas3.create_image(0, 0, anchor=tk.NW, image=state["photos"][0], tags="img")
            self.canvas3.tag_raise("badge3")
            return

        w4 = max(self.canvas4.winfo_width(), 1)
        h4 = max(self.canvas4.winfo_height(), 1)
        v3 = self._get_view(
            state["images"][0],
            row_shift_x,
            row_shift_y,
            glob_rot + row_shift_rot,
            w3,
            h3,
            idx=0,
            align_scale=row_shift_scale,
            preview_images=state["preview_images"],
            preview_scales=state["preview_scales"],
            rotated_cache=state["rotated_cache"],
            last_rot=state["last_rot"],
            rotated_preview_cache=state["rotated_preview_cache"],
            last_rot_preview=state["last_rot_preview"],
            adj_vars=state["adj_vars"],
        )
        v4 = self._get_view(
            state["images"][1],
            row_shift_x + int(round(off_x * row_shift_scale)),
            row_shift_y + int(round(off_y * row_shift_scale)),
            glob_rot + row_shift_rot + rot,
            w4,
            h4,
            idx=1,
            align_scale=row_shift_scale * img2_scale,
            preview_images=state["preview_images"],
            preview_scales=state["preview_scales"],
            rotated_cache=state["rotated_cache"],
            last_rot=state["last_rot"],
            rotated_preview_cache=state["rotated_preview_cache"],
            last_rot_preview=state["last_rot_preview"],
            adj_vars=state["adj_vars"],
        )

        state["photos"][0] = ImageTk.PhotoImage(v3)
        state["photos"][1] = ImageTk.PhotoImage(v4)
        if self.canvas3.find_withtag("img"):
            self.canvas3.itemconfig("img", image=state["photos"][0])
            self.canvas3.coords("img", 0, 0)
        else:
            self.canvas3.create_image(0, 0, anchor=tk.NW, image=state["photos"][0], tags="img")
        if self.canvas4.find_withtag("img"):
            self.canvas4.itemconfig("img", image=state["photos"][1])
            self.canvas4.coords("img", 0, 0)
        else:
            self.canvas4.create_image(0, 0, anchor=tk.NW, image=state["photos"][1], tags="img")
        self.canvas3.tag_raise("badge3")
        self.canvas4.tag_raise("badge4")

    def _get_view(self, img, off_x, off_y, rotation, canvas_w, canvas_h, idx=None, align_scale=1.0,
                  preview_images=None, preview_scales=None, rotated_cache=None, last_rot=None,
                  rotated_preview_cache=None, last_rot_preview=None, adj_vars=None):
        placeholder = Image.new("RGB", (canvas_w, canvas_h), (30, 30, 30))
        if img is None:
            return placeholder

        source = img
        source_scale = 1.0
        preview_images = self.preview_images if preview_images is None else preview_images
        preview_scales = self.preview_scales if preview_scales is None else preview_scales
        rot_cache = self._rotated_cache if rotated_cache is None else rotated_cache
        rot_last = self._last_rot if last_rot is None else last_rot
        rotated_preview_cache = self._rotated_preview_cache if rotated_preview_cache is None else rotated_preview_cache
        last_rot_preview = self._last_rot_preview if last_rot_preview is None else last_rot_preview
        adj_vars = self.adj_vars if adj_vars is None else adj_vars
        if self._interacting and idx is not None and preview_images[idx] is not None:
            source = preview_images[idx]
            source_scale = preview_scales[idx]
            rot_cache = rotated_preview_cache
            rot_last = last_rot_preview

        if rotation != 0.0:
            if idx is not None and rot_last[idx] == rotation and rot_cache[idx] is not None:
                working = rot_cache[idx]
            else:
                working = source.rotate(-rotation, resample=Image.BICUBIC, expand=False)
                if idx is not None:
                    rot_cache[idx] = working
                    rot_last[idx] = rotation
        else:
            working = source

        zoom = max(self.zoom / source_scale, 1e-6)
        off_x = off_x * source_scale
        off_y = off_y * source_scale
        cx = working.width / 2.0
        cy = working.height / 2.0
        scaled_zoom = zoom * align_scale
        paste_x = self.pan_x + off_x * zoom + (1.0 - align_scale) * cx * zoom
        paste_y = self.pan_y + off_y * zoom + (1.0 - align_scale) * cy * zoom

        src_x0_f = max(0.0, (0.0 - paste_x) / scaled_zoom)
        src_y0_f = max(0.0, (0.0 - paste_y) / scaled_zoom)
        src_x1_f = min(float(working.width), (canvas_w - paste_x) / scaled_zoom)
        src_y1_f = min(float(working.height), (canvas_h - paste_y) / scaled_zoom)

        if src_x1_f <= src_x0_f or src_y1_f <= src_y0_f:
            return placeholder

        src_x0 = max(0, int(math.floor(src_x0_f)))
        src_y0 = max(0, int(math.floor(src_y0_f)))
        src_x1 = min(working.width, int(math.ceil(src_x1_f)))
        src_y1 = min(working.height, int(math.ceil(src_y1_f)))

        if src_x1 <= src_x0 or src_y1 <= src_y0:
            return placeholder

        if self._interacting:
            resample = Image.NEAREST
        else:
            resample = Image.LANCZOS if zoom <= 1.0 else Image.BICUBIC

        region = working.crop((src_x0, src_y0, src_x1, src_y1))

        dst_x0 = int(round(paste_x + src_x0_f * scaled_zoom))
        dst_y0 = int(round(paste_y + src_y0_f * scaled_zoom))
        dst_x1 = int(round(paste_x + src_x1_f * scaled_zoom))
        dst_y1 = int(round(paste_y + src_y1_f * scaled_zoom))

        dst_x0 = max(0, min(canvas_w, dst_x0))
        dst_y0 = max(0, min(canvas_h, dst_y0))
        dst_x1 = max(0, min(canvas_w, dst_x1))
        dst_y1 = max(0, min(canvas_h, dst_y1))

        target_w = dst_x1 - dst_x0
        target_h = dst_y1 - dst_y0
        if target_w <= 0 or target_h <= 0:
            return placeholder

        if region.size != (target_w, target_h):
            region = region.resize((target_w, target_h), resample=resample)

        if idx is not None:
            region = self._apply_adjustments(region, idx, adj_vars=adj_vars)

        result = Image.new("RGB", (canvas_w, canvas_h), (30, 30, 30))
        result.paste(region, (dst_x0, dst_y0))
        return result

    def _draw_cursors(self):
        cx, cy = self.cursor_pos
        for canvas in self._iter_visible_canvases():
            canvas.delete("cursor")
            w = canvas.winfo_width()
            h = canvas.winfo_height()
            if w < 2 or h < 2:
                continue
            canvas.create_line(0, cy, w, cy, fill="#ff3333", tags="cursor", width=1)
            canvas.create_line(cx, 0, cx, h, fill="#ff3333", tags="cursor", width=1)
            r = 6
            canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                               outline="#ff3333", tags="cursor", width=1)
            canvas.tag_raise("cursor")

    def _get_alignment_values(self):
        try:
            return (
                int(float(self.off_x_var.get())),
                int(float(self.off_y_var.get())),
                float(self.rot_var.get()),
                float(self.glob_rot_var.get()),
            )
        except ValueError:
            return 0, 0, 0.0, 0.0

    def _get_img2_scale(self):
        try:
            return max(0.1, float(self.img2_scale_var.get()))
        except ValueError:
            return 1.0

    def _get_compare_row_alignment_values(self):
        try:
            return (
                int(float(self.compare_row_off_x_var.get())),
                int(float(self.compare_row_off_y_var.get())),
                float(self.compare_row_rot_var.get()),
                float(self.compare_row_glob_rot_var.get()),
            )
        except ValueError:
            return 0, 0, 0.0, 0.0

    def _get_compare_row_img2_scale(self):
        try:
            return max(0.1, float(self.compare_row_img2_scale_var.get()))
        except ValueError:
            return 1.0

    def _get_compare_row_shift_values(self):
        try:
            return (
                int(float(self.compare_row_shift_x_var.get())),
                int(float(self.compare_row_shift_y_var.get())),
                float(self.compare_row_shift_rot_var.get()),
                max(0.1, float(self.compare_row_shift_scale_var.get())),
            )
        except ValueError:
            return 0, 0, 0.0, 1.0

    def _rotate_display_point(self, x, y, cx, cy, rot_deg):
        if not rot_deg:
            return x, y
        theta = math.radians(rot_deg)
        dx, dy = x - cx, y - cy
        return (
            cx + dx * math.cos(theta) - dy * math.sin(theta),
            cy + dx * math.sin(theta) + dy * math.cos(theta),
        )

    def _unrotate_display_point(self, x, y, cx, cy, rot_deg):
        if not rot_deg:
            return x, y
        theta = math.radians(rot_deg)
        dx, dy = x - cx, y - cy
        return (
            cx + dx * math.cos(theta) + dy * math.sin(theta),
            cy - dx * math.sin(theta) + dy * math.cos(theta),
        )

    def _expected_align_canvas(self):
        return 0 if len(self._align_pts_img1) <= len(self._align_pts_img2) else 1

    def _expected_compare_align_canvas(self):
        return 0 if len(self._compare_row_align_pts_img1) <= len(self._compare_row_align_pts_img2) else 1

    def _expected_row_align_canvas(self):
        return 0 if len(self._row_align_pts_top) <= len(self._row_align_pts_bottom) else 1

    def _on_canvas_leave(self, event):
        if event.widget is self.canvas2:
            self._align_guide_cursor = None
            self.canvas2.delete("align_guide")
        if event.widget is self.canvas4:
            self._compare_row_align_guide_cursor = None
            self.canvas4.delete("compare_align_guide")
        if self.crop_mode_var.get() and self._crop_corner1 is not None:
            self.canvas1.delete("crop_preview")
            self.canvas2.delete("crop_preview")

    def _img1_to_canvas1(self, img_x, img_y, glob_rot):
        if self.images[0] is not None:
            cx0, cy0 = self.images[0].width / 2.0, self.images[0].height / 2.0
        else:
            cx0 = cy0 = 0.0
        rx, ry = self._rotate_display_point(img_x, img_y, cx0, cy0, glob_rot)
        return self.pan_x + rx * self.zoom, self.pan_y + ry * self.zoom

    def _img1_to_canvas2(self, img_x, img_y, off_x, off_y, total_rot):
        if self.images[1] is not None:
            cx2, cy2 = self.images[1].width / 2.0, self.images[1].height / 2.0
        else:
            cx2 = cy2 = 0.0
        scale = self._get_img2_scale()
        rx, ry = self._rotate_display_point(img_x, img_y, cx2, cy2, total_rot)
        rx = cx2 + (rx - cx2) * scale
        ry = cy2 + (ry - cy2) * scale
        return (
            self.pan_x + off_x * self.zoom + rx * self.zoom,
            self.pan_y + off_y * self.zoom + ry * self.zoom,
        )

    def _compare_img1_to_canvas3(self, img_x, img_y, glob_rot, row_shift_rot=0.0, row_shift_scale=1.0,
                                 row_shift_x=0, row_shift_y=0):
        if self.compare_row_images[0] is not None:
            cx0, cy0 = self.compare_row_images[0].width / 2.0, self.compare_row_images[0].height / 2.0
        else:
            cx0 = cy0 = 0.0
        rx, ry = self._rotate_display_point(img_x, img_y, cx0, cy0, glob_rot + row_shift_rot)
        rx = cx0 + (rx - cx0) * row_shift_scale
        ry = cy0 + (ry - cy0) * row_shift_scale
        return self.pan_x + row_shift_x * self.zoom + rx * self.zoom, self.pan_y + row_shift_y * self.zoom + ry * self.zoom

    def _compare_img1_to_canvas4(self, img_x, img_y, off_x, off_y, total_rot,
                                 row_shift_x=0, row_shift_y=0, row_shift_scale=1.0):
        if self.compare_row_images[1] is not None:
            cx2, cy2 = self.compare_row_images[1].width / 2.0, self.compare_row_images[1].height / 2.0
        else:
            cx2 = cy2 = 0.0
        rx, ry = self._rotate_display_point(img_x, img_y, cx2, cy2, total_rot)
        rx = cx2 + (rx - cx2) * row_shift_scale
        ry = cy2 + (ry - cy2) * row_shift_scale
        return (
            self.pan_x + (row_shift_x + off_x * row_shift_scale) * self.zoom + rx * self.zoom,
            self.pan_y + (row_shift_y + off_y * row_shift_scale) * self.zoom + ry * self.zoom,
        )

    def _canvas_to_img1(self, canvas_x, canvas_y, canvas_is_2=False):
        _, _, _, glob_rot = self._get_alignment_values()
        rx = (canvas_x - self.pan_x) / self.zoom
        ry = (canvas_y - self.pan_y) / self.zoom
        cx0 = self.images[0].width / 2.0 if self.images[0] else 0.0
        cy0 = self.images[0].height / 2.0 if self.images[0] else 0.0
        return self._unrotate_display_point(rx, ry, cx0, cy0, glob_rot)

    def _canvas_to_img2(self, canvas_x, canvas_y):
        off_x, off_y, rot, glob_rot = self._get_alignment_values()
        total_rot = glob_rot + rot
        scale = self._get_img2_scale()
        rx = (canvas_x - self.pan_x) / self.zoom - off_x
        ry = (canvas_y - self.pan_y) / self.zoom - off_y
        cx2 = self.images[1].width / 2.0 if self.images[1] else 0.0
        cy2 = self.images[1].height / 2.0 if self.images[1] else 0.0
        rx = cx2 + (rx - cx2) / scale
        ry = cy2 + (ry - cy2) / scale
        return self._unrotate_display_point(rx, ry, cx2, cy2, total_rot)

    def _canvas_to_compare_img1(self, canvas_x, canvas_y):
        row_shift_x, row_shift_y, row_shift_rot, row_shift_scale = self._get_compare_row_shift_values()
        _, _, _, glob_rot = self._get_compare_row_alignment_values()
        rx = (canvas_x - self.pan_x) / self.zoom - row_shift_x
        ry = (canvas_y - self.pan_y) / self.zoom - row_shift_y
        cx0 = self.compare_row_images[0].width / 2.0 if self.compare_row_images[0] else 0.0
        cy0 = self.compare_row_images[0].height / 2.0 if self.compare_row_images[0] else 0.0
        rx = cx0 + (rx - cx0) / row_shift_scale
        ry = cy0 + (ry - cy0) / row_shift_scale
        return self._unrotate_display_point(rx, ry, cx0, cy0, glob_rot + row_shift_rot)

    def _canvas_to_compare_img2(self, canvas_x, canvas_y):
        off_x, off_y, rot, glob_rot = self._get_compare_row_alignment_values()
        row_shift_x, row_shift_y, row_shift_rot, row_shift_scale = self._get_compare_row_shift_values()
        total_rot = glob_rot + row_shift_rot + rot
        internal_scale = self._get_compare_row_img2_scale()
        total_scale = row_shift_scale * internal_scale
        rx = (canvas_x - self.pan_x) / self.zoom - row_shift_x - off_x * row_shift_scale
        ry = (canvas_y - self.pan_y) / self.zoom - row_shift_y - off_y * row_shift_scale
        cx2 = self.compare_row_images[1].width / 2.0 if self.compare_row_images[1] else 0.0
        cy2 = self.compare_row_images[1].height / 2.0 if self.compare_row_images[1] else 0.0
        rx = cx2 + (rx - cx2) / max(total_scale, 1e-6)
        ry = cy2 + (ry - cy2) / max(total_scale, 1e-6)
        return self._unrotate_display_point(rx, ry, cx2, cy2, total_rot)
