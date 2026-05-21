import math
import tkinter as tk
from tkinter import colorchooser, messagebox, simpledialog

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageTk

from .constants import _PRESET_COLOURS


class AnnotationMixin:
    def _draw_align_guide(self):
        self.canvas2.delete("align_guide")
        if not self.align_mode_var.get():
            return
        n1 = len(self._align_pts_img1)
        n2 = len(self._align_pts_img2)
        if n1 < 2 or n1 != n2 + 1:
            return
        off_x, off_y, rot, glob_rot = self._get_alignment_values()
        total_rot = glob_rot + rot
        prev_img2 = self._align_pts_img2[-1]
        gx, gy = self._img2_to_canvas2(prev_img2[0], prev_img2[1], off_x, off_y, total_rot)
        p1a = np.array(self._align_pts_img1[-2])
        p1b = np.array(self._align_pts_img1[-1])
        r_canvas = float(np.linalg.norm(p1b - p1a)) * self.zoom
        self.canvas2.create_oval(
            gx - r_canvas, gy - r_canvas, gx + r_canvas, gy + r_canvas,
            outline="#ffaa00", width=1, dash=(4, 4), tags="align_guide")
        if self._align_guide_cursor is not None:
            cx, cy = self._align_guide_cursor
            dx, dy = cx - gx, cy - gy
            dist = math.hypot(dx, dy)
            if dist > 1.0:
                lx = gx + dx / dist * r_canvas
                ly = gy + dy / dist * r_canvas
                self.canvas2.create_line(gx, gy, lx, ly,
                                         fill="#ffaa00", width=1, dash=(4, 4),
                                         tags="align_guide")
        self.canvas2.tag_raise("align_guide")
        self.canvas2.tag_raise("align_pts")

    def _on_annot_mode_change(self):
        if self.annot_mode_var.get():
            self.level_mode_var.set(False)
            self.canvas1.delete("level_line")
            self.canvas2.delete("level_line")
            self._level_start = None
            self.align_mode_var.set(False)
            self.canvas1.delete("align_pts")
            self.canvas2.delete("align_pts")
            self.crop_mode_var.set(False)
            self._crop_corner1 = None
            self.canvas1.delete("crop_preview")
            self.canvas2.delete("crop_preview")
        active = (self.annot_mode_var.get() or self.level_mode_var.get()
                  or self.align_mode_var.get() or self.crop_mode_var.get())
        cur = "tcross" if active else "crosshair"
        self.canvas1.config(cursor=cur)
        self.canvas2.config(cursor=cur)

    def _on_level_mode_change(self):
        if not self.level_mode_var.get():
            self.canvas1.delete("level_line")
            self.canvas2.delete("level_line")
            self._level_start = None
        if self.level_mode_var.get():
            self.annot_mode_var.set(False)
            self.align_mode_var.set(False)
            self.canvas1.delete("align_pts")
            self.canvas2.delete("align_pts")
            self.crop_mode_var.set(False)
            self._crop_corner1 = None
            self.canvas1.delete("crop_preview")
            self.canvas2.delete("crop_preview")
        active = (self.level_mode_var.get() or self.annot_mode_var.get()
                  or self.align_mode_var.get() or self.crop_mode_var.get())
        cur = "tcross" if active else "crosshair"
        self.canvas1.config(cursor=cur)
        self.canvas2.config(cursor=cur)

    def _on_align_mode_change(self):
        if self.align_mode_var.get():
            self.level_mode_var.set(False)
            self.canvas1.delete("level_line")
            self.canvas2.delete("level_line")
            self._level_start = None
            self.annot_mode_var.set(False)
            self.crop_mode_var.set(False)
            self._crop_corner1 = None
            self.canvas1.delete("crop_preview")
            self.canvas2.delete("crop_preview")
        else:
            self._align_guide_cursor = None
            self.canvas1.delete("align_pts")
            self.canvas2.delete("align_pts")
            self.canvas2.delete("align_guide")
        active = (self.align_mode_var.get() or self.annot_mode_var.get()
                  or self.level_mode_var.get() or self.crop_mode_var.get())
        cur = "tcross" if active else "crosshair"
        self.canvas1.config(cursor=cur)
        self.canvas2.config(cursor=cur)
        self._update_align_status()

    def _update_align_status(self):
        n1 = len(self._align_pts_img1)
        n2 = len(self._align_pts_img2)
        n_pairs = min(n1, n2)
        can_apply = n_pairs >= 2 and self.images[0] and self.images[1]
        self._align_apply_btn.config(state=tk.NORMAL if can_apply else tk.DISABLED)
        if self.align_mode_var.get():
            next_target = "Image 1" if self._expected_align_canvas() == 0 else "Image 2"
            self.status_var.set(
                f"Point align  -  Image 1: {n1} pt(s)  |  Image 2: {n2} pt(s)  |  "
                f"{'Ready  -  click Apply' if can_apply else 'Next click: ' + next_target}"
            )

    def _add_align_point(self, event):
        canvas_is_2 = (event.widget == self.canvas2)
        expected_canvas = self._expected_align_canvas()
        if int(canvas_is_2) != expected_canvas:
            expected_name = "Image 2" if expected_canvas else "Image 1"
            self.status_var.set(f"Point align  -  next click should be on {expected_name}.")
            return
        if canvas_is_2:
            if self.images[1] is None:
                return
            off_x, off_y, rot, glob_rot = self._get_alignment_values()
            total_rot = glob_rot + rot
            cx2 = self.images[1].width / 2.0
            cy2 = self.images[1].height / 2.0
            click_x, click_y = event.x, event.y
            n1_now = len(self._align_pts_img1)
            n2_now = len(self._align_pts_img2)
            if n1_now >= 2 and n1_now == n2_now + 1:
                prev_img2 = self._align_pts_img2[-1]
                gx, gy = self._img2_to_canvas2(prev_img2[0], prev_img2[1], off_x, off_y, total_rot)
                p1a = np.array(self._align_pts_img1[-2])
                p1b = np.array(self._align_pts_img1[-1])
                r_canvas = float(np.linalg.norm(p1b - p1a)) * self.zoom
                dx, dy = click_x - gx, click_y - gy
                dist = math.hypot(dx, dy)
                if dist > 1.0:
                    click_x = gx + dx / dist * r_canvas
                    click_y = gy + dy / dist * r_canvas
                else:
                    click_x = gx + r_canvas
            rx = (click_x - self.pan_x) / self.zoom - off_x
            ry = (click_y - self.pan_y) / self.zoom - off_y
            img2_x, img2_y = self._unrotate_display_point(rx, ry, cx2, cy2, total_rot)
            self._align_pts_img2.append((img2_x, img2_y))
        else:
            if self.images[0] is None:
                return
            img_x, img_y = self._canvas_to_img1(event.x, event.y, canvas_is_2=False)
            self._align_pts_img1.append((img_x, img_y))
        self._update_align_status()
        self._schedule_render()

    def _clear_align_pts(self):
        self._align_pts_img1.clear()
        self._align_pts_img2.clear()
        self._align_guide_cursor = None
        self._align_apply_btn.config(state=tk.DISABLED)
        self.canvas1.delete("align_pts")
        self.canvas2.delete("align_pts")
        self.canvas2.delete("align_guide")
        self._update_align_status()

    def _apply_point_alignment(self):
        n = min(len(self._align_pts_img1), len(self._align_pts_img2))
        if n < 2 or self.images[0] is None or self.images[1] is None:
            return

        p1 = np.array(self._align_pts_img1[:n], dtype=float)
        p2 = np.array(self._align_pts_img2[:n], dtype=float)

        glob_rot = float(self.glob_rot_var.get())
        g = math.radians(glob_rot)
        cos_g, sin_g = math.cos(g), math.sin(g)
        r_g = np.array([[cos_g, -sin_g], [sin_g, cos_g]])

        c1 = np.array([self.images[0].width / 2.0, self.images[0].height / 2.0])
        c2 = np.array([self.images[1].width / 2.0, self.images[1].height / 2.0])

        u = (r_g @ (p1 - c1).T).T + c1
        u_mean = u.mean(axis=0)
        d_mean = (p2 - c2).mean(axis=0)
        u_c = u - u_mean
        d_c = (p2 - c2) - d_mean

        h = d_c.T @ u_c
        u_s, _, vt = np.linalg.svd(h)
        r_new = vt.T @ u_s.T
        if np.linalg.det(r_new) < 0:
            vt[-1] *= -1
            r_new = vt.T @ u_s.T

        total_rot = math.degrees(math.atan2(r_new[1, 0], r_new[0, 0]))
        delta_rot = total_rot - glob_rot
        off = u_mean - c2 - r_new @ d_mean

        self.off_x_var.set(str(int(round(off[0]))))
        self.off_y_var.set(str(int(round(off[1]))))
        self.rot_var.set(f"{delta_rot:.2f}")
        self._schedule_render()
        self.status_var.set(
            f"Alignment applied  -  offset ({off[0]:.0f}, {off[1]:.0f}) px  | "
            f"rotation {delta_rot:.2f}deg  | from {n} point pair(s)"
        )

    def _img2_to_canvas2(self, img2_x, img2_y, off_x, off_y, total_rot):
        cx2 = self.images[1].width / 2.0 if self.images[1] else 0.0
        cy2 = self.images[1].height / 2.0 if self.images[1] else 0.0
        rx, ry = self._rotate_display_point(img2_x, img2_y, cx2, cy2, total_rot)
        return (
            self.pan_x + off_x * self.zoom + rx * self.zoom,
            self.pan_y + off_y * self.zoom + ry * self.zoom,
        )

    def _draw_align_pts(self):
        self.canvas1.delete("align_pts")
        self.canvas2.delete("align_pts")
        if not self.align_mode_var.get():
            return
        off_x, off_y, rot, glob_rot = self._get_alignment_values()
        total_rot = glob_rot + rot
        r = 7
        for i, (px, py) in enumerate(self._align_pts_img1):
            cx, cy = self._img1_to_canvas1(px, py, glob_rot)
            self.canvas1.create_oval(cx - r, cy - r, cx + r, cy + r,
                                     outline="#88ffff", width=2, tags="align_pts")
            self.canvas1.create_text(cx, cy, text=str(i + 1), fill="#88ffff",
                                     font=("TkDefaultFont", 7, "bold"), tags="align_pts")
        if self.images[1] is not None:
            for i, (px, py) in enumerate(self._align_pts_img2):
                cx, cy = self._img2_to_canvas2(px, py, off_x, off_y, total_rot)
                self.canvas2.create_oval(cx - r, cy - r, cx + r, cy + r,
                                         outline="#88ffff", width=2, tags="align_pts")
                self.canvas2.create_text(cx, cy, text=str(i + 1), fill="#88ffff",
                                         font=("TkDefaultFont", 7, "bold"), tags="align_pts")
        self.canvas1.tag_raise("align_pts")
        self.canvas2.tag_raise("align_pts")
        self._draw_align_guide()

    def _pick_colour(self):
        popup = tk.Toplevel(self.root)
        popup.title("Marker colour")
        popup.resizable(False, False)
        popup.configure(bg="#2b2b2b")
        popup.transient(self.root)
        popup.grab_set()
        cols = 4
        for i, col in enumerate(_PRESET_COLOURS):
            r, c = divmod(i, cols)
            tk.Button(popup, bg=col, width=3, height=1, relief=tk.RIDGE,
                      cursor="hand2",
                      command=lambda clr=col: self._set_annot_colour(clr, popup)
                      ).grid(row=r, column=c, padx=3, pady=3)
        rows_used = (len(_PRESET_COLOURS) + cols - 1) // cols
        tk.Button(popup, text="Custom...", bg="#555", fg="white",
                  relief=tk.FLAT, padx=8, pady=3, cursor="hand2",
                  command=lambda: self._custom_colour(popup)
                  ).grid(row=rows_used, column=0, columnspan=cols,
                         padx=3, pady=(4, 3), sticky="ew")

    def _set_annot_colour(self, colour, popup):
        self.annot_colour = colour
        self.annot_colour_btn.config(bg=colour)
        popup.destroy()

    def _custom_colour(self, popup):
        popup.destroy()
        result = colorchooser.askcolor(color=self.annot_colour,
                                       title="Custom marker colour")
        if result and result[1]:
            self.annot_colour = result[1]
            self.annot_colour_btn.config(bg=self.annot_colour)

    def _on_left_press(self, event):
        if self.crop_mode_var.get():
            self._on_crop_click(event)
        elif self.level_mode_var.get():
            self._level_start = (event.x, event.y)
            event.widget.delete("level_line")
        elif self.align_mode_var.get():
            self._add_align_point(event)
        elif self.annot_mode_var.get():
            self._place_annotation(event)
        else:
            self._on_pan_start(event)

    def _on_b1_motion(self, event):
        if self.crop_mode_var.get():
            pass
        elif self.level_mode_var.get():
            if self._level_start:
                event.widget.delete("level_line")
                x0, y0 = self._level_start
                event.widget.create_line(x0, y0, event.x, event.y,
                                         fill="#ffff44", width=2,
                                         tags="level_line", dash=(6, 4))
        elif self.align_mode_var.get():
            pass
        elif not self.annot_mode_var.get():
            self._on_pan(event)

    def _on_left_release(self, event):
        if not self.level_mode_var.get() or self._level_start is None:
            return
        x0, y0 = self._level_start
        x1, y1 = event.x, event.y
        event.widget.delete("level_line")
        self._level_start = None
        dx, dy = x1 - x0, y1 - y0
        if abs(dx) > 3 or abs(dy) > 3:
            if dy < 0:
                dx, dy = -dx, -dy
            angle = math.degrees(math.atan2(dx, dy))
            try:
                current = float(self.glob_rot_var.get())
            except ValueError:
                current = 0.0
            self.glob_rot_var.set(f"{current + angle:.2f}")
            self._schedule_render()

    def _place_annotation(self, event):
        if self.images[0] is None and self.images[1] is None:
            return
        img1_x, img1_y = self._canvas_to_img1(event.x, event.y)
        img2_x, img2_y = self._canvas_to_img2(event.x, event.y)
        label = ""
        if self.annot_label_var.get():
            label = simpledialog.askstring("Label", "Annotation label (leave blank for none):",
                                           parent=self.root) or ""
        colour = self.annot_colour
        if colour not in self.colour_labels:
            lbl = simpledialog.askstring(
                "New annotation colour",
                f"First use of colour {colour}.\n"
                "Add a legend label for this colour (leave blank to skip):",
                parent=self.root,
            ) or ""
            self.colour_labels[colour] = lbl
        self.annotations.append({
            "img1_x": img1_x,
            "img1_y": img1_y,
            "img2_x": img2_x,
            "img2_y": img2_y,
            "radius": self.annot_radius_var.get(),
            "colour": colour,
            "label": label,
        })
        self._schedule_render()

    def _on_right_click(self, event):
        if not self.annotations:
            return
        off_x, off_y, rot, glob_rot = self._get_alignment_values()
        total_rot = glob_rot + rot
        canvas_is_2 = (event.widget == self.canvas2)
        tolerance = 30
        closest, min_dist = None, float("inf")
        for i, ann in enumerate(self.annotations):
            if canvas_is_2 and self.images[1] is not None:
                cx, cy = self._img2_to_canvas2(ann["img2_x"], ann["img2_y"],
                                               off_x, off_y, total_rot)
            else:
                cx, cy = self._img1_to_canvas1(ann["img1_x"], ann["img1_y"], glob_rot)
            d = math.hypot(event.x - cx, event.y - cy)
            if d < tolerance and d < min_dist:
                min_dist, closest = d, i
        if closest is not None:
            del self.annotations[closest]
            self._schedule_render()

    def _clear_annotations(self):
        if not self.annotations:
            return
        if not messagebox.askyesno("Clear all markers",
                                   "Delete all annotation markers? This cannot be undone.",
                                   parent=self.root):
            return
        self.annotations.clear()
        self.canvas1.delete("annotations")
        self.canvas2.delete("annotations")
        self.canvas1.delete("legend")
        self.canvas2.delete("legend")

    def _edit_colour_labels(self):
        if not self.colour_labels:
            messagebox.showinfo("Edit labels",
                                "No colour labels yet.\n"
                                "Annotate with a colour first to create a label.",
                                parent=self.root)
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("Edit colour labels")
        dlg.configure(bg="#2b2b2b")
        dlg.resizable(False, False)
        dlg.transient(self.root)

        tk.Label(dlg, text="Edit legend label for each annotation colour:",
                 bg="#2b2b2b", fg="#ccc",
                 font=("TkDefaultFont", 9)).pack(padx=12, pady=(10, 6), anchor=tk.W)

        entries = {}
        frame = tk.Frame(dlg, bg="#2b2b2b")
        frame.pack(padx=12, pady=4, fill=tk.X)

        for colour, label in self.colour_labels.items():
            row = tk.Frame(frame, bg="#2b2b2b")
            row.pack(fill=tk.X, pady=3)
            tk.Label(row, bg=colour, width=3, height=1,
                     relief=tk.FLAT).pack(side=tk.LEFT, padx=(0, 8))
            tk.Label(row, text=colour, bg="#2b2b2b", fg="#888",
                     font=("TkFixedFont", 9), width=8).pack(side=tk.LEFT)
            var = tk.StringVar(value=label)
            tk.Entry(row, textvariable=var, bg="#444", fg="white",
                     insertbackground="white", relief=tk.FLAT,
                     width=26).pack(side=tk.LEFT, padx=(6, 0))
            entries[colour] = var

        confirmed = [False]

        def on_ok():
            confirmed[0] = True
            dlg.destroy()

        btn_row = tk.Frame(dlg, bg="#2b2b2b")
        btn_row.pack(pady=(8, 10))
        tk.Button(btn_row, text="OK", command=on_ok,
                  bg="#336633", fg="white", relief=tk.FLAT, padx=14, pady=4,
                  cursor="hand2").pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text="Cancel", command=dlg.destroy,
                  bg="#555", fg="white", relief=tk.FLAT, padx=10, pady=4,
                  cursor="hand2").pack(side=tk.LEFT, padx=6)

        dlg.wait_window()
        if confirmed[0]:
            for colour, var in entries.items():
                self.colour_labels[colour] = var.get()
            self._schedule_render()

    def _set_app_icon(self):
        try:
            # Mesh grid icon
            sz = 64
            m = 4           # outer margin
            g = 6           # grid inset from background edge
            n = 5           # cells per side
            img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.rectangle([m, m, sz - m - 1, sz - m - 1],
                         fill="#1a3a5c", outline="#6ab0dc", width=1)
            g0 = m + g
            g1 = sz - m - g - 1
            for i in range(n + 1):
                t = i / n
                x = round(g0 + t * (g1 - g0))
                y = round(g0 + t * (g1 - g0))
                d.line([(x, g0), (x, g1)], fill="#4a9eff", width=1)
                d.line([(g0, y), (g1, y)], fill="#4a9eff", width=1)
            dr = 2
            for i in range(n + 1):
                for j in range(n + 1):
                    cx = round(g0 + (i / n) * (g1 - g0))
                    cy = round(g0 + (j / n) * (g1 - g0))
                    d.ellipse([cx - dr, cy - dr, cx + dr, cy + dr], fill="#b0deff")
            photo = ImageTk.PhotoImage(img)
            self.root.iconphoto(True, photo)
            self._icon_photo = photo
        except Exception:
            pass

    def _apply_adjustments(self, img, idx):
        d = self.adj_vars[idx]
        blacks = d["blacks"].get()
        whites = d["whites"].get()
        brightness = d["brightness"].get()
        contrast = d["contrast"].get()
        if (blacks == 0.0 and whites == 255.0
                and abs(brightness - 1.0) < 1e-3
                and abs(contrast - 1.0) < 1e-3):
            return img
        if img.mode != "RGB":
            img = img.convert("RGB")
        if blacks != 0.0 or whites != 255.0:
            scale = 255.0 / max(whites - blacks, 1.0)
            arr = np.array(img, dtype=np.float32)
            arr = (arr - blacks) * scale
            img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        if abs(brightness - 1.0) >= 1e-3:
            img = ImageEnhance.Brightness(img).enhance(brightness)
        if abs(contrast - 1.0) >= 1e-3:
            img = ImageEnhance.Contrast(img).enhance(contrast)
        return img

    def _reset_adjustments(self):
        for d in self.adj_vars:
            d["brightness"].set(1.0)
            d["contrast"].set(1.0)
            d["blacks"].set(0.0)
            d["whites"].set(255.0)
        self._schedule_render()

    def _reset_image_adjustments(self, idx):
        d = self.adj_vars[idx]
        d["brightness"].set(1.0)
        d["contrast"].set(1.0)
        d["blacks"].set(0.0)
        d["whites"].set(255.0)
        self._schedule_render()

    def _draw_annotations(self):
        off_x, off_y, rot, glob_rot = self._get_alignment_values()
        total_rot = glob_rot + rot
        mode = self.mode_var.get()
        self.canvas1.delete("annotations")
        self.canvas2.delete("annotations")
        if not self.annotations:
            self.canvas1.delete("legend")
            self.canvas2.delete("legend")
            return
        for ann in self.annotations:
            ix1, iy1 = ann["img1_x"], ann["img1_y"]
            ix2, iy2 = ann["img2_x"], ann["img2_y"]
            colour = ann["colour"]
            label = ann.get("label", "")
            r = max(3, ann["radius"] * self.zoom)

            cx, cy = self._img1_to_canvas1(ix1, iy1, glob_rot)
            self.canvas1.create_oval(cx - r, cy - r, cx + r, cy + r,
                                     outline=colour, width=self.annot_width_var.get(), tags="annotations")
            if label:
                self.canvas1.create_text(cx + r + 5, cy, text=label, fill=colour,
                                         anchor=tk.W, tags="annotations",
                                         font=("TkDefaultFont", self.annot_label_size_var.get(), "bold"))

            if mode == "sidebyside" and self.images[1] is not None:
                cx2, cy2 = self._img2_to_canvas2(ix2, iy2, off_x, off_y, total_rot)
                self.canvas2.create_oval(cx2 - r, cy2 - r, cx2 + r, cy2 + r,
                                         outline=colour, width=self.annot_width_var.get(), tags="annotations")
                if label:
                    self.canvas2.create_text(cx2 + r + 5, cy2, text=label, fill=colour,
                                             anchor=tk.W, tags="annotations",
                                             font=("TkDefaultFont", self.annot_label_size_var.get(), "bold"))

        self._draw_legend(self.canvas1)
        if mode == "sidebyside":
            self._draw_legend(self.canvas2)
        self.canvas1.tag_raise("annotations")
        if mode == "sidebyside":
            self.canvas2.tag_raise("annotations")
        self.canvas1.tag_raise("legend")
        if mode == "sidebyside":
            self.canvas2.tag_raise("legend")

    def _legend_data(self):
        counts = {}
        for ann in self.annotations:
            counts[ann["colour"]] = counts.get(ann["colour"], 0) + 1
        return [(c, self.colour_labels.get(c, ""), n) for c, n in counts.items()]

    def _draw_legend(self, canvas):
        import tkinter.font as tkfont

        canvas.delete("legend")
        data = self._legend_data()
        if not data:
            return
        w, h = canvas.winfo_width(), canvas.winfo_height()
        if w < 2 or h < 2:
            return
        lsz = self.canvas_legend_size_var.get()
        pad = max(5, lsz // 2)
        row_h = max(16, int(lsz * 1.8))
        swatch = max(8, int(lsz * 0.85))
        fnt = tkfont.Font(size=lsz)
        texts = [
            f" {label}  (n={count})" if label else f" (n={count})"
            for _, label, count in data
        ]
        box_w = max((fnt.measure(t) for t in texts), default=60) + pad * 2 + swatch + 4
        box_h = pad * 2 + len(data) * row_h
        x0 = w - pad - box_w
        y0 = h - pad - box_h
        canvas.create_rectangle(x0, y0, x0 + box_w, y0 + box_h,
                                fill="#1e1e1e", outline="#555555", width=1,
                                tags="legend")
        for i, ((colour, _label, _count), text) in enumerate(zip(data, texts)):
            row_y = y0 + pad + i * row_h
            sy = row_y + (row_h - swatch) // 2
            canvas.create_rectangle(x0 + pad, sy, x0 + pad + swatch, sy + swatch,
                                    fill=colour, outline="", tags="legend")
            canvas.create_text(x0 + pad + swatch + 4, row_y + row_h // 2,
                               text=text, fill=colour, anchor=tk.W,
                               font=("TkDefaultFont", lsz), tags="legend")
