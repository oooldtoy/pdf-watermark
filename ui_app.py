"""
PDF 水印小工具 - 现代图形界面 (ui_app.py)
提供拖拽导入、实时预览、参数自由定制、矢量水印与整页图片化防篡改功能。
"""

import os
import re
import sys
import time
import datetime
import threading
import tkinter as tk
from tkinter import ttk, colorchooser, filedialog, messagebox
from typing import List, Optional
from PIL import Image, ImageTk

from watermark_engine import (
    WatermarkConfig,
    FontManager,
    apply_watermark_to_pdf,
    render_preview_image
)
from pypdf import PdfReader

# 尝试引入 TkinterDnD 拖拽库
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_DND = True
except ImportError:
    HAS_DND = False


def parse_dnd_files(event_data: str) -> List[str]:
    """解析 Windows 拖拽事件传入的文件路径，支持包含空格的路径"""
    pattern = r"\{([^}]+)\}|(\S+)"
    matches = re.findall(pattern, event_data)
    result = []
    for m in matches:
        p = m[0] if m[0] else m[1]
        p = p.strip('"\'')
        if os.path.isfile(p) and p.lower().endswith(".pdf"):
            result.append(os.path.abspath(p))
        elif os.path.isdir(p):
            for root, _, files in os.walk(p):
                for f in files:
                    if f.lower().endswith(".pdf"):
                        result.append(os.path.abspath(os.path.join(root, f)))
    return result


class ScrollableFrame(ttk.Frame):
    """带自适应滚动条的可滚动容器"""
    def __init__(self, container, *args, **kwargs):
        super().__init__(container, *args, **kwargs)
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0, bg="#F8FAFC")
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_content = ttk.Frame(self.canvas, style="Card.TFrame")

        self.scrollable_content.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_content, anchor="nw")
        self.canvas.configure(xscrollcommand=None, yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.bind_mouse_scroll(self.canvas)
        self.bind_mouse_scroll(self.scrollable_content)

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def bind_mouse_scroll(self, widget):
        widget.bind("<MouseWheel>", self._on_mousewheel, add="+")
        for child in widget.winfo_children():
            self.bind_mouse_scroll(child)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class WatermarkApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("PDF 水印小工具 - 支持防去除整页图片化")
        self.root.geometry("1200x840")
        self.root.minsize(1050, 720)

        # 核心数据状态
        self.file_list: List[str] = []
        self.current_preview_file: Optional[str] = None
        self.current_preview_page: int = 0
        self.total_preview_pages: int = 1
        self.preview_image_ref = None  # 防止 PIL 图片被垃圾回收
        self.debounce_timer = None
        self.is_processing = False
        self.last_output_dir = ""

        # 水印配置对象
        self.config = WatermarkConfig()

        # 界面初始化
        self._init_styles()
        self._build_ui()

        # 启动后默认加载一次仿真预览
        self.root.after(150, self.update_preview)

    def _init_styles(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # 主题色彩规范
        self.c_bg = "#F1F5F9"
        self.c_card = "#FFFFFF"
        self.c_primary = "#2563EB"
        self.c_primary_active = "#1D4ED8"
        self.c_text = "#0F172A"
        self.c_text_muted = "#64748B"
        self.c_border = "#E2E8F0"

        self.root.configure(bg=self.c_bg)

        style.configure("TFrame", background=self.c_bg)
        style.configure("Card.TFrame", background=self.c_card)
        style.configure("TLabel", background=self.c_card, foreground=self.c_text, font=("Microsoft YaHei UI", 9))
        style.configure("Header.TLabel", font=("Microsoft YaHei UI", 12, "bold"), foreground="#1E293B")
        style.configure("Section.TLabel", font=("Microsoft YaHei UI", 10, "bold"), foreground="#334155")
        style.configure("Muted.TLabel", foreground=self.c_text_muted, font=("Microsoft YaHei UI", 8))

        style.configure("TLabelframe", background=self.c_card, relief="solid", borderwidth=1)
        style.configure("TLabelframe.Label", background=self.c_card, foreground="#1E293B", font=("Microsoft YaHei UI", 9, "bold"))

        style.configure("Primary.TButton", font=("Microsoft YaHei UI", 10, "bold"), foreground="#FFFFFF", background=self.c_primary)
        style.map("Primary.TButton", background=[("active", self.c_primary_active), ("disabled", "#94A3B8")])

        style.configure("Chip.TButton", font=("Microsoft YaHei UI", 8), padding=2)

    def _build_ui(self):
        # 顶部标题栏
        top_bar = tk.Frame(self.root, bg=self.c_primary, height=48)
        top_bar.pack(side="top", fill="x")

        lbl_app_title = tk.Label(
            top_bar,
            text=" 📄 PDF 水印助手  |  矢量水印 & 整页图片化防篡改",
            font=("Microsoft YaHei UI", 11, "bold"),
            fg="#FFFFFF",
            bg=self.c_primary
        )
        lbl_app_title.pack(side="left", padx=15, pady=10)

        # 主工作区分为左右两栏
        main_paned = ttk.PanedWindow(self.root, orient="horizontal")
        main_paned.pack(fill="both", expand=True, padx=12, pady=10)

        # 左侧控制面板 (可滚动)
        left_container = ttk.Frame(main_paned, width=540)
        main_paned.add(left_container, weight=1)

        self.scroll_frame = ScrollableFrame(left_container)
        self.scroll_frame.pack(fill="both", expand=True)
        ctrl_parent = self.scroll_frame.scrollable_content

        # 右侧预览与任务队列区
        right_container = ttk.Frame(main_paned, width=600)
        main_paned.add(right_container, weight=1)

        # 构建左侧各控制模块
        self._build_file_section(ctrl_parent)
        self._build_text_section(ctrl_parent)
        self._build_layout_section(ctrl_parent)
        self._build_appearance_section(ctrl_parent)
        self._build_security_section(ctrl_parent)
        self._build_action_section(ctrl_parent)

        # 构建右侧各控制模块
        self._build_preview_section(right_container)
        self._build_queue_section(right_container)

    # ------------------ 左侧控制模块 ------------------

    def _build_file_section(self, parent):
        box = ttk.LabelFrame(parent, text=" 1. 待处理 PDF 文件 (支持拖拽导入)", padding=8)
        box.pack(fill="x", padx=10, pady=6)

        # 拖拽投放提示区
        drop_bg = "#F8FAFC"
        self.drop_area = tk.Frame(box, bg=drop_bg, relief="groove", bd=1, height=65)
        self.drop_area.pack(fill="x", pady=4)
        self.drop_area.pack_propagate(False)

        self.lbl_drop = tk.Label(
            self.drop_area,
            text=" 📥 将 PDF 文件或文件夹拖入此处，或使用下方按钮选择 ",
            font=("Microsoft YaHei UI", 9),
            fg="#475569",
            bg=drop_bg
        )
        self.lbl_drop.pack(expand=True)

        if HAS_DND:
            self.drop_area.drop_target_register(DND_FILES)
            self.drop_area.dnd_bind("<<Drop>>", self._on_files_dropped)
            self.lbl_drop.drop_target_register(DND_FILES)
            self.lbl_drop.dnd_bind("<<Drop>>", self._on_files_dropped)

        btn_row = ttk.Frame(box)
        btn_row.pack(fill="x", pady=4)

        ttk.Button(btn_row, text="📄 选择文件...", command=self._choose_files).pack(side="left", padx=3)
        ttk.Button(btn_row, text="📁 选择文件夹...", command=self._choose_folder).pack(side="left", padx=3)
        ttk.Button(btn_row, text="🗑️ 清空列表", command=self._clear_files).pack(side="left", padx=3)

        self.lbl_file_count = ttk.Label(box, text="当前未选择文件 (预览显示 A4 演示样稿)", style="Muted.TLabel")
        self.lbl_file_count.pack(anchor="w", pady=2)

    def _build_text_section(self, parent):
        box = ttk.LabelFrame(parent, text=" 2. 水印文字内容", padding=8)
        box.pack(fill="x", padx=10, pady=6)

        self.txt_watermark = tk.Text(box, height=3, font=("Microsoft YaHei UI", 10), wrap="word", relief="solid", bd=1)
        self.txt_watermark.insert("1.0", self.config.text)
        self.txt_watermark.pack(fill="x", pady=3)
        self.txt_watermark.bind("<KeyRelease>", lambda e: self.on_param_change())

        # 常用变量快捷插入按钮
        tag_row = ttk.Frame(box)
        tag_row.pack(fill="x", pady=2)

        ttk.Label(tag_row, text="快捷添加:", style="Muted.TLabel").pack(side="left", padx=2)

        def append_tag(tag):
            cur = self.txt_watermark.get("1.0", "end-1c").strip()
            new_text = f"{cur} {tag}".strip() if cur else tag
            self.txt_watermark.delete("1.0", "end")
            self.txt_watermark.insert("1.0", new_text)
            self.on_param_change()

        today_str = datetime.date.today().strftime("%Y-%m-%d")
        ttk.Button(tag_row, text=f"+ 日期 ({today_str})", style="Chip.TButton", command=lambda: append_tag(today_str)).pack(side="left", padx=2)
        ttk.Button(tag_row, text="+ 内部借阅 严禁外传", style="Chip.TButton", command=lambda: append_tag("内部借阅 严禁外传")).pack(side="left", padx=2)
        ttk.Button(tag_row, text="+ 仅供资质审核使用", style="Chip.TButton", command=lambda: append_tag("仅供资质审核使用")).pack(side="left", padx=2)

    def _build_layout_section(self, parent):
        box = ttk.LabelFrame(parent, text=" 3. 布局与密集程度", padding=8)
        box.pack(fill="x", padx=10, pady=6)

        # 模式切换
        mode_row = ttk.Frame(box)
        mode_row.pack(fill="x", pady=2)

        self.var_mode = tk.StringVar(value=self.config.mode)
        rb1 = ttk.Radiobutton(mode_row, text="全屏平铺矩阵 (推荐)", value="tiled", variable=self.var_mode, command=self._on_mode_change)
        rb1.pack(side="left", padx=5)
        rb2 = ttk.Radiobutton(mode_row, text="单水印居中", value="single", variable=self.var_mode, command=self._on_mode_change)
        rb2.pack(side="left", padx=15)

        # 密集度快捷滑块
        self.tiled_controls = ttk.Frame(box)
        self.tiled_controls.pack(fill="x", pady=4)

        dens_row = ttk.Frame(self.tiled_controls)
        dens_row.pack(fill="x", pady=2)
        ttk.Label(dens_row, text="密集度预设:").pack(side="left")
        self.var_density_preset = tk.IntVar(value=3)
        self.slider_density = ttk.Scale(dens_row, from_=1, to=5, variable=self.var_density_preset, command=self._on_density_preset_change)
        self.slider_density.pack(side="left", fill="x", expand=True, padx=8)
        self.lbl_density_name = ttk.Label(dens_row, text="适中", width=6)
        self.lbl_density_name.pack(side="left")

        # 详细间距控制 (水平间距、垂直间距)
        spacing_row = ttk.Frame(self.tiled_controls)
        spacing_row.pack(fill="x", pady=3)

        ttk.Label(spacing_row, text="水平间距:").grid(row=0, column=0, sticky="w")
        self.var_sx = tk.DoubleVar(value=self.config.spacing_x)
        self.scale_sx = ttk.Scale(spacing_row, from_=80, to=400, variable=self.var_sx, command=lambda v: self._on_spacing_scale_change())
        self.scale_sx.grid(row=0, column=1, sticky="ew", padx=6)
        self.lbl_sx = ttk.Label(spacing_row, text=f"{int(self.config.spacing_x)} pt", width=6)
        self.lbl_sx.grid(row=0, column=2, sticky="w")

        ttk.Label(spacing_row, text="垂直间距:").grid(row=1, column=0, sticky="w", pady=4)
        self.var_sy = tk.DoubleVar(value=self.config.spacing_y)
        self.scale_sy = ttk.Scale(spacing_row, from_=60, to=350, variable=self.var_sy, command=lambda v: self._on_spacing_scale_change())
        self.scale_sy.grid(row=1, column=1, sticky="ew", padx=6, pady=4)
        self.lbl_sy = ttk.Label(spacing_row, text=f"{int(self.config.spacing_y)} pt", width=6)
        self.lbl_sy.grid(row=1, column=2, sticky="w", pady=4)

        spacing_row.columnconfigure(1, weight=1)

        # 奇偶行错位交错勾选
        self.var_stagger = tk.BooleanVar(value=self.config.stagger)
        chk_stagger = ttk.Checkbutton(self.tiled_controls, text="奇偶行错位交错分布 (覆盖更均匀全面)", variable=self.var_stagger, command=self.on_param_change)
        chk_stagger.pack(anchor="w", pady=2)

    def _build_appearance_section(self, parent):
        box = ttk.LabelFrame(parent, text=" 4. 倾斜角度与外观样式", padding=8)
        box.pack(fill="x", padx=10, pady=6)

        # 倾斜角度
        ang_row = ttk.Frame(box)
        ang_row.pack(fill="x", pady=2)
        ttk.Label(ang_row, text="倾斜角度:").pack(side="left")
        self.var_angle = tk.DoubleVar(value=self.config.angle)
        self.scale_angle = ttk.Scale(ang_row, from_=-90, to=90, variable=self.var_angle, command=self._on_angle_change)
        self.scale_angle.pack(side="left", fill="x", expand=True, padx=6)
        self.lbl_angle = ttk.Label(ang_row, text=f"{int(self.config.angle)}°", width=5)
        self.lbl_angle.pack(side="left")

        # 快捷角度按钮
        chip_row = ttk.Frame(box)
        chip_row.pack(fill="x", pady=2)
        ttk.Label(chip_row, text="快捷角度:", style="Muted.TLabel").pack(side="left", padx=2)
        for ang in [-45, -30, 0, 30, 45]:
            lbl = f"{ang}°" if ang != 0 else "0° (水平)"
            ttk.Button(chip_row, text=lbl, style="Chip.TButton", command=lambda a=ang: self._set_angle(a)).pack(side="left", padx=2)

        # 字体与字号
        font_row = ttk.Frame(box)
        font_row.pack(fill="x", pady=4)

        ttk.Label(font_row, text="字体:").pack(side="left")
        available_fonts = FontManager.get_font_names()
        self.var_font = tk.StringVar(value=FontManager.get_default_font())
        cmb_font = ttk.Combobox(font_row, textvariable=self.var_font, values=available_fonts, state="readonly", width=12)
        cmb_font.pack(side="left", padx=6)
        cmb_font.bind("<<ComboboxSelected>>", lambda e: self.on_param_change())

        ttk.Label(font_row, text="字号:").pack(side="left", padx=(10, 0))
        self.var_fontsize = tk.IntVar(value=self.config.font_size)
        scale_size = ttk.Scale(font_row, from_=12, to=72, variable=self.var_fontsize, command=lambda v: self._on_fontsize_change())
        scale_size.pack(side="left", fill="x", expand=True, padx=6)
        self.lbl_fontsize = ttk.Label(font_row, text=f"{self.config.font_size} pt", width=6)
        self.lbl_fontsize.pack(side="left")

        # 透明度与颜色
        color_row = ttk.Frame(box)
        color_row.pack(fill="x", pady=4)

        ttk.Label(color_row, text="透明度:").pack(side="left")
        self.var_opacity = tk.DoubleVar(value=int(self.config.opacity * 100))
        scale_op = ttk.Scale(color_row, from_=5, to=100, variable=self.var_opacity, command=lambda v: self._on_opacity_change())
        scale_op.pack(side="left", fill="x", expand=True, padx=6)
        self.lbl_opacity = ttk.Label(color_row, text=f"{int(self.config.opacity*100)}%", width=5)
        self.lbl_opacity.pack(side="left")

        # 颜色块及选取
        ttk.Label(color_row, text="颜色:").pack(side="left", padx=(10, 4))
        self.var_color = tk.StringVar(value=self.config.color)
        self.color_swatch = tk.Label(color_row, text="  ", bg=self.config.color, relief="solid", bd=1, width=3)
        self.color_swatch.pack(side="left", padx=2)
        ttk.Button(color_row, text="调色板...", command=self._pick_color, style="Chip.TButton").pack(side="left", padx=4)

        # 快捷颜色芯片
        quick_colors = [("#888888", "经典灰"), ("#DC2626", "警示红"), ("#2563EB", "公章蓝"), ("#1E293B", "深黑")]
        for hex_c, c_name in quick_colors:
            ttk.Button(color_row, text=c_name, style="Chip.TButton", command=lambda c=hex_c: self._set_color(c)).pack(side="left", padx=1)

    def _build_security_section(self, parent):
        box = ttk.LabelFrame(parent, text=" 5. 输出模式与防篡改设置", padding=8)
        box.pack(fill="x", padx=10, pady=6)

        self.var_rasterize = tk.BooleanVar(value=True)

        rb_rast = ttk.Radiobutton(
            box,
            text="🛡️ 水印后整页图片化 (推荐：防篡改/不可去除，水印熔合为像素)",
            value=True,
            variable=self.var_rasterize,
            command=self._on_rasterize_toggle
        )
        rb_rast.pack(anchor="w", pady=2)

        # DPI 选项框架
        self.dpi_frame = ttk.Frame(box)
        self.dpi_frame.pack(fill="x", padx=20, pady=2)

        self.var_dpi = tk.IntVar(value=self.config.dpi)
        ttk.Radiobutton(self.dpi_frame, text="150 DPI (轻量快速)", value=150, variable=self.var_dpi).pack(side="left", padx=4)
        ttk.Radiobutton(self.dpi_frame, text="200 DPI (高清标准 推荐)", value=200, variable=self.var_dpi).pack(side="left", padx=8)
        ttk.Radiobutton(self.dpi_frame, text="300 DPI (印刷级超清)", value=300, variable=self.var_dpi).pack(side="left", padx=4)

        rb_vec = ttk.Radiobutton(
            box,
            text="⚡ 直接文字水印 (矢量模式：文件体积轻小，原文字仍可选中复制)",
            value=False,
            variable=self.var_rasterize,
            command=self._on_rasterize_toggle
        )
        rb_vec.pack(anchor="w", pady=(4, 2))

        # 输出目录选项
        out_dir_frame = ttk.Frame(box)
        out_dir_frame.pack(fill="x", pady=4)

        self.var_out_same_dir = tk.BooleanVar(value=True)
        chk_same = ttk.Checkbutton(out_dir_frame, text="保存至源文件同目录下 (文件名追加 _watermarked)", variable=self.var_out_same_dir, command=self._toggle_custom_out_dir)
        chk_same.pack(anchor="w")

        self.custom_dir_frame = ttk.Frame(out_dir_frame)
        self.custom_dir_frame.pack(fill="x", pady=2)
        self.var_custom_dir = tk.StringVar(value="")
        self.ent_custom_dir = ttk.Entry(self.custom_dir_frame, textvariable=self.var_custom_dir)
        self.ent_custom_dir.pack(side="left", fill="x", expand=True, padx=(18, 4))
        self.btn_browse_out = ttk.Button(self.custom_dir_frame, text="浏览...", command=self._choose_custom_output_dir)
        self.btn_browse_out.pack(side="left")
        self.custom_dir_frame.pack_forget()

    def _build_action_section(self, parent):
        act_box = ttk.Frame(parent)
        act_box.pack(fill="x", padx=10, pady=12)

        self.btn_start = ttk.Button(act_box, text="🚀 开始批量生成水印 PDF", style="Primary.TButton", command=self.start_processing)
        self.btn_start.pack(fill="x", ipady=6, pady=2)

        self.btn_open_folder = ttk.Button(act_box, text="📁 打开输出文件夹", command=self.open_output_folder)
        self.btn_open_folder.pack(fill="x", pady=2)

    # ------------------ 右侧预览与队列模块 ------------------

    def _build_preview_section(self, parent):
        preview_box = ttk.LabelFrame(parent, text=" 👁️ 水印实时效果预览 (所见即所得)", padding=6)
        preview_box.pack(fill="both", expand=True, padx=4, pady=4)

        # 预览顶部控制条
        top_ctrl = ttk.Frame(preview_box)
        top_ctrl.pack(fill="x", pady=2)

        self.lbl_preview_title = ttk.Label(top_ctrl, text="示例文档 (A4 仿真演示)", style="Section.TLabel")
        self.lbl_preview_title.pack(side="left", padx=4)

        self.btn_prev_page = ttk.Button(top_ctrl, text="◀ 上一页", width=8, command=self._prev_page, state="disabled")
        self.btn_prev_page.pack(side="right", padx=2)
        self.lbl_page_indicator = ttk.Label(top_ctrl, text="1 / 1", style="Muted.TLabel")
        self.lbl_page_indicator.pack(side="right", padx=4)
        self.btn_next_page = ttk.Button(top_ctrl, text="下一页 ▶", width=8, command=self._next_page, state="disabled")
        self.btn_next_page.pack(side="right", padx=2)

        # 画布区域 (带浅灰背景与页面拟真边框)
        self.canvas_preview = tk.Canvas(preview_box, bg="#E2E8F0", highlightthickness=0)
        self.canvas_preview.pack(fill="both", expand=True, padx=4, pady=4)

    def _build_queue_section(self, parent):
        queue_box = ttk.LabelFrame(parent, text=" 📋 任务列表与处理进度", padding=6)
        queue_box.pack(fill="x", padx=4, pady=4)

        # 进度条与状态
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_bar = ttk.Progressbar(queue_box, variable=self.progress_var, maximum=100.0)
        self.progress_bar.pack(fill="x", pady=3)

        self.lbl_status = ttk.Label(queue_box, text="就绪。请添加 PDF 文件并点击开始生成。", foreground="#334155")
        self.lbl_status.pack(anchor="w", pady=1)

        # 简易日志/列表控制
        self.lst_files = tk.Listbox(queue_box, height=4, font=("Consolas", 8), selectmode="single")
        self.lst_files.pack(fill="x", pady=2)
        self.lst_files.bind("<<ListboxSelect>>", self._on_file_select_in_list)

    # ------------------ 事件与参数联动处理 ------------------

    def on_param_change(self):
        """当任何水印参数发生变动时，触发防抖更新预览"""
        if self.debounce_timer:
            self.root.after_cancel(self.debounce_timer)
        self.debounce_timer = self.root.after(100, self.update_preview)

    def _collect_config_from_ui(self) -> WatermarkConfig:
        """从 UI 控件中读取最新的水印配置"""
        text = self.txt_watermark.get("1.0", "end-1c")
        if not text.strip():
            text = "机密文件"

        cfg = WatermarkConfig(
            text=text,
            font_name=self.var_font.get(),
            font_size=int(self.var_fontsize.get()),
            color=self.var_color.get(),
            opacity=float(self.var_opacity.get()) / 100.0,
            angle=float(self.var_angle.get()),
            mode=self.var_mode.get(),
            spacing_x=float(self.var_sx.get()),
            spacing_y=float(self.var_sy.get()),
            stagger=self.var_stagger.get(),
            layer="overlay",
            rasterize=self.var_rasterize.get(),
            dpi=int(self.var_dpi.get()),
            quality=88
        )
        return cfg

    def update_preview(self):
        """重新计算并绘制右侧预览图"""
        cfg = self._collect_config_from_ui()

        # 计算画布可用尺寸
        w_avail = max(200, self.canvas_preview.winfo_width())
        h_avail = max(200, self.canvas_preview.winfo_height())

        try:
            pil_img = render_preview_image(
                self.current_preview_file,
                cfg,
                page_index=self.current_preview_page,
                max_preview_size=(w_avail - 20, h_avail - 20)
            )

            self.preview_image_ref = ImageTk.PhotoImage(pil_img)
            self.canvas_preview.delete("all")

            # 居中显示
            cx = w_avail // 2
            cy = h_avail // 2
            self.canvas_preview.create_image(cx, cy, image=self.preview_image_ref)
        except Exception as e:
            print(f"Preview render error: {e}")

    def _on_mode_change(self):
        m = self.var_mode.get()
        if m == "single":
            self.tiled_controls.pack_forget()
        else:
            self.tiled_controls.pack(fill="x", pady=4)
        self.on_param_change()

    def _on_density_preset_change(self, val):
        val = int(round(float(val)))
        # 1: 稀疏, 2: 较稀疏, 3: 适中, 4: 密集, 5: 极密
        presets = {
            1: (260.0, 200.0, "稀疏"),
            2: (220.0, 170.0, "较稀疏"),
            3: (180.0, 140.0, "适中"),
            4: (140.0, 110.0, "密集"),
            5: (100.0, 80.0, "极密"),
        }
        sx, sy, name = presets.get(val, (180.0, 140.0, "适中"))
        self.var_sx.set(sx)
        self.var_sy.set(sy)
        self.lbl_sx.config(text=f"{int(sx)} pt")
        self.lbl_sy.config(text=f"{int(sy)} pt")
        self.lbl_density_name.config(text=name)
        self.on_param_change()

    def _on_spacing_scale_change(self):
        sx = int(self.var_sx.get())
        sy = int(self.var_sy.get())
        self.lbl_sx.config(text=f"{sx} pt")
        self.lbl_sy.config(text=f"{sy} pt")
        self.lbl_density_name.config(text="自定义")
        self.on_param_change()

    def _on_angle_change(self, val):
        deg = int(round(float(val)))
        self.lbl_angle.config(text=f"{deg}°")
        self.on_param_change()

    def _set_angle(self, deg: int):
        self.var_angle.set(deg)
        self.lbl_angle.config(text=f"{deg}°")
        self.on_param_change()

    def _on_fontsize_change(self):
        sz = int(self.var_fontsize.get())
        self.lbl_fontsize.config(text=f"{sz} pt")
        self.on_param_change()

    def _on_opacity_change(self):
        op = int(self.var_opacity.get())
        self.lbl_opacity.config(text=f"{op}%")
        self.on_param_change()

    def _pick_color(self):
        cur = self.var_color.get()
        chosen = colorchooser.askcolor(initialcolor=cur, title="选取水印颜色")
        if chosen and chosen[1]:
            self._set_color(chosen[1])

    def _set_color(self, hex_color: str):
        self.var_color.set(hex_color)
        self.color_swatch.config(bg=hex_color)
        self.on_param_change()

    def _on_rasterize_toggle(self):
        if self.var_rasterize.get():
            self.dpi_frame.pack(fill="x", padx=20, pady=2)
        else:
            self.dpi_frame.pack_forget()

    def _toggle_custom_out_dir(self):
        if self.var_out_same_dir.get():
            self.custom_dir_frame.pack_forget()
        else:
            self.custom_dir_frame.pack(fill="x", pady=2)

    def _choose_custom_output_dir(self):
        d = filedialog.askdirectory(title="选择水印输出目录")
        if d:
            self.var_custom_dir.set(d)

    # ------------------ 文件管理与拖拽 ------------------

    def _on_files_dropped(self, event):
        files = parse_dnd_files(event.data)
        if files:
            self._add_files(files)

    def _choose_files(self):
        files = filedialog.askopenfilenames(
            title="选择要添加水印的 PDF 文件",
            filetypes=[("PDF 文档", "*.pdf"), ("所有文件", "*.*")]
        )
        if files:
            self._add_files(list(files))

    def _choose_folder(self):
        folder = filedialog.askdirectory(title="选择包含 PDF 的文件夹")
        if folder:
            found = []
            for root, _, fs in os.walk(folder):
                for f in fs:
                    if f.lower().endswith(".pdf"):
                        found.append(os.path.join(root, f))
            if found:
                self._add_files(found)
            else:
                messagebox.showinfo("提示", "所选文件夹内未发现 PDF 文件。")

    def _add_files(self, paths: List[str]):
        new_count = 0
        for p in paths:
            abs_p = os.path.abspath(p)
            if abs_p not in self.file_list:
                self.file_list.append(abs_p)
                new_count += 1

        self._refresh_file_list_ui()
        if self.file_list and not self.current_preview_file:
            self._set_preview_file(self.file_list[0])

    def _clear_files(self):
        self.file_list.clear()
        self.current_preview_file = None
        self.current_preview_page = 0
        self.total_preview_pages = 1
        self._refresh_file_list_ui()
        self.lbl_preview_title.config(text="示例文档 (A4 仿真演示)")
        self.btn_prev_page.config(state="disabled")
        self.btn_next_page.config(state="disabled")
        self.lbl_page_indicator.config(text="1 / 1")
        self.update_preview()

    def _refresh_file_list_ui(self):
        self.lst_files.delete(0, "end")
        for f in self.file_list:
            self.lst_files.insert("end", f"⏳ {os.path.basename(f)}")

        cnt = len(self.file_list)
        if cnt == 0:
            self.lbl_file_count.config(text="当前未选择文件 (预览显示 A4 演示样稿)")
        else:
            self.lbl_file_count.config(text=f"已添加 {cnt} 个 PDF 文件待处理")

    def _set_preview_file(self, path: str):
        self.current_preview_file = path
        self.current_preview_page = 0
        try:
            reader = PdfReader(path)
            self.total_preview_pages = len(reader.pages)
        except Exception:
            self.total_preview_pages = 1

        base_name = os.path.basename(path)
        self.lbl_preview_title.config(text=f"{base_name} (共 {self.total_preview_pages} 页)")
        self._update_page_nav_buttons()
        self.update_preview()

    def _update_page_nav_buttons(self):
        cur = self.current_preview_page + 1
        tot = self.total_preview_pages
        self.lbl_page_indicator.config(text=f"{cur} / {tot}")
        self.btn_prev_page.config(state="normal" if self.current_preview_page > 0 else "disabled")
        self.btn_next_page.config(state="normal" if self.current_preview_page < self.total_preview_pages - 1 else "disabled")

    def _prev_page(self):
        if self.current_preview_page > 0:
            self.current_preview_page -= 1
            self._update_page_nav_buttons()
            self.update_preview()

    def _next_page(self):
        if self.current_preview_page < self.total_preview_pages - 1:
            self.current_preview_page += 1
            self._update_page_nav_buttons()
            self.update_preview()

    def _on_file_select_in_list(self, event):
        sel = self.lst_files.curselection()
        if sel:
            idx = sel[0]
            if idx < len(self.file_list):
                self._set_preview_file(self.file_list[idx])

    # ------------------ 水印生成任务执行 ------------------

    def start_processing(self):
        if self.is_processing:
            return
        if not self.file_list:
            messagebox.showwarning("提示", "请先选择或拖入需要打水印的 PDF 文件！")
            return

        # 检查输出目录
        if not self.var_out_same_dir.get():
            custom_dir = self.var_custom_dir.get().strip()
            if not custom_dir or not os.path.isdir(custom_dir):
                messagebox.showerror("错误", "请选择有效的自定义输出目录！")
                return

        self.is_processing = True
        self.btn_start.config(state="disabled", text="⏳ 正在生成水印中...")
        self.progress_var.set(0.0)

        cfg = self._collect_config_from_ui()

        # 启动后台工作线程
        t = threading.Thread(target=self._worker_process, args=(cfg,), daemon=True)
        t.start()

    def _worker_process(self, cfg: WatermarkConfig):
        total_files = len(self.file_list)
        success_count = 0
        fail_count = 0

        for f_idx, in_path in enumerate(self.file_list):
            base_dir = os.path.dirname(in_path)
            file_name = os.path.basename(in_path)
            name_no_ext, ext = os.path.splitext(file_name)

            suffix = "_protected" if cfg.rasterize else "_watermarked"
            out_filename = f"{name_no_ext}{suffix}{ext}"

            if self.var_out_same_dir.get():
                out_path = os.path.join(base_dir, out_filename)
                self.last_output_dir = base_dir
            else:
                out_dir = self.var_custom_dir.get().strip()
                out_path = os.path.join(out_dir, out_filename)
                self.last_output_dir = out_dir

            # 更新 UI 状态
            self.root.after(0, self._update_task_status, f_idx, f"🔄 处理中: {file_name}")

            def on_progress(cur, tot, desc):
                fraction = (f_idx + (cur / max(1, tot))) / total_files
                self.root.after(0, self._update_progress_ui, fraction * 100.0, f"[{f_idx + 1}/{total_files}] {file_name}: {desc}")

            try:
                apply_watermark_to_pdf(in_path, out_path, cfg, progress_callback=on_progress)
                success_count += 1
                self.root.after(0, self._update_list_item, f_idx, f"✅ {file_name} -> 完成")
            except Exception as e:
                fail_count += 1
                print(f"Error processing {in_path}: {e}")
                self.root.after(0, self._update_list_item, f_idx, f"❌ {file_name} -> 失败: {e}")

        self.root.after(0, self._on_all_finished, success_count, fail_count)

    def _update_task_status(self, idx: int, status_text: str):
        self.lbl_status.config(text=status_text)
        self.lst_files.selection_clear(0, "end")
        self.lst_files.selection_set(idx)
        self.lst_files.see(idx)

    def _update_progress_ui(self, pct: float, desc: str):
        self.progress_var.set(pct)
        self.lbl_status.config(text=desc)

    def _update_list_item(self, idx: int, text: str):
        if idx < self.lst_files.size():
            self.lst_files.delete(idx)
            self.lst_files.insert(idx, text)

    def _on_all_finished(self, success_count: int, fail_count: int):
        self.is_processing = False
        self.btn_start.config(state="normal", text="🚀 开始批量生成水印 PDF")
        self.progress_var.set(100.0)

        msg = f"处理完成！\n成功: {success_count} 个文件\n失败: {fail_count} 个文件"
        self.lbl_status.config(text=f"全部处理完毕。成功: {success_count}，失败: {fail_count}")

        if success_count > 0:
            if messagebox.askyesno("处理成功", f"{msg}\n\n是否立即打开输出文件夹？"):
                self.open_output_folder()
        else:
            messagebox.showerror("处理失败", msg)

    def open_output_folder(self):
        target_dir = self.last_output_dir
        if not target_dir or not os.path.exists(target_dir):
            if self.file_list:
                target_dir = os.path.dirname(self.file_list[0])
            elif not self.var_out_same_dir.get():
                target_dir = self.var_custom_dir.get().strip()

        if target_dir and os.path.exists(target_dir):
            try:
                os.startfile(target_dir)
            except Exception as e:
                messagebox.showerror("无法打开文件夹", str(e))
        else:
            messagebox.showinfo("提示", "暂无输出目录或目录不存在。")


def create_app():
    """工厂函数：根据系统环境创建主窗口并运行"""
    # 优先使用 TkinterDnD 支持拖拽，无则优雅降级
    if HAS_DND:
        try:
            root = TkinterDnD.Tk()
        except Exception:
            root = tk.Tk()
    else:
        root = tk.Tk()

    app = WatermarkApp(root)
    return root, app


if __name__ == "__main__":
    # 开启 Windows 高分屏 (High DPI) 缩放清晰度支持
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    root, app = create_app()
    root.update_idletasks()
    width = 1200
    height = 840
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = max(0, (screen_width - width) // 2)
    y = max(0, (screen_height - height) // 2)
    root.geometry(f"{width}x{height}+{x}+{y}")
    root.mainloop()

