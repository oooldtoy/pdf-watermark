"""
PDF 水印核心引擎 (watermark_engine.py)
负责水印图层生成、矢量合并叠加与实时预览渲染。
"""

import os
import io
import math
from dataclasses import dataclass
from typing import Optional, Callable, Tuple, List
from PIL import Image

import pypdf
from pypdf import PdfReader, PdfWriter
import pypdfium2 as pdfium
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


class FontManager:
    """字体管理器：自动检测并注册 Windows 系统常见中文字体，确保中文水印正常渲染不乱码"""
    _registered = False
    _available_fonts = {}

    @classmethod
    def init_fonts(cls):
        if cls._registered:
            return cls._available_fonts

        candidates = {
            "微软雅黑": ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyh.ttf"],
            "黑体": ["C:/Windows/Fonts/simhei.ttf"],
            "宋体": ["C:/Windows/Fonts/simsun.ttc"],
            "楷体": ["C:/Windows/Fonts/simkai.ttf"],
            "仿宋": ["C:/Windows/Fonts/simfang.ttf"],
            "Arial": ["C:/Windows/Fonts/arial.ttf"],
        }

        for name, paths in candidates.items():
            for p in paths:
                if os.path.exists(p):
                    try:
                        pdfmetrics.registerFont(TTFont(name, p))
                        cls._available_fonts[name] = p
                        break
                    except Exception as e:
                        print(f"Failed to register font {name} from {p}: {e}")

        # 如果没有中文字体注册成功，回退使用 Helvetica
        if not cls._available_fonts:
            cls._available_fonts["Helvetica"] = "Builtin"

        cls._registered = True
        return cls._available_fonts

    @classmethod
    def get_font_names(cls) -> List[str]:
        cls.init_fonts()
        return list(cls._available_fonts.keys())

    @classmethod
    def get_default_font(cls) -> str:
        cls.init_fonts()
        if "微软雅黑" in cls._available_fonts:
            return "微软雅黑"
        if "黑体" in cls._available_fonts:
            return "黑体"
        return list(cls._available_fonts.keys())[0]


@dataclass
class WatermarkConfig:
    text: str = "机密文件 严禁外传"
    font_name: str = "微软雅黑"
    font_size: int = 26
    color: str = "#888888"       # 16进制颜色
    opacity: float = 0.25        # 0.05 ~ 1.0
    angle: float = -30.0         # 倾斜角度 (-90 ~ 90)
    mode: str = "tiled"          # "tiled" (平铺网格) 或 "single" (居中单个)
    spacing_x: float = 180.0     # 平铺水平间距 (点)
    spacing_y: float = 140.0     # 平铺垂直间距 (点)
    stagger: bool = True         # 是否奇偶行错位交错排布
    layer: str = "overlay"       # "overlay" (覆盖在上方) 或 "underlay" (在下方背景)
    rasterize: bool = True       # 是否整页图片化 (防篡改/防去除)
    dpi: int = 200               # 图片化 DPI (150, 200, 300)
    quality: int = 90            # 图像压缩质量 (1~100)


def create_watermark_layer(width: float, height: float, config: WatermarkConfig) -> io.BytesIO:
    """根据页面宽高与水印配置，生成仅包含水印的透明单页 PDF 字节流"""
    FontManager.init_fonts()
    font_name = config.font_name if config.font_name in FontManager.get_font_names() else FontManager.get_default_font()

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))

    # 解析颜色并附带透明度
    try:
        base_color = colors.HexColor(config.color)
    except Exception:
        base_color = colors.HexColor("#888888")

    c.setFillColor(base_color, alpha=max(0.01, min(1.0, config.opacity)))
    c.setFont(font_name, config.font_size)

    lines = config.text.replace("\\n", "\n").split("\n")
    line_height = config.font_size * 1.3
    total_text_h = (len(lines) - 1) * line_height

    def draw_multiline(x: float, y: float):
        c.saveState()
        c.translate(x, y)
        c.rotate(config.angle)
        start_y = total_text_h / 2.0
        for i, line in enumerate(lines):
            c.drawCentredString(0, start_y - i * line_height, line)
        c.restoreState()

    if config.mode == "single":
        # 单水印居中
        draw_multiline(width / 2.0, height / 2.0)
    else:
        # 平铺矩阵模式
        sx = max(50.0, float(config.spacing_x))
        sy = max(40.0, float(config.spacing_y))

        # 扩充范围以确保倾斜角度大时也能完全覆盖边界
        margin = max(width, height) * 0.25
        x_min = -margin
        x_max = width + margin
        y_min = -margin
        y_max = height + margin

        row_idx = 0
        y = y_min
        while y <= y_max:
            offset_x = (sx * 0.5) if (config.stagger and row_idx % 2 == 1) else 0.0
            x = x_min + offset_x
            while x <= x_max:
                draw_multiline(x, y)
                x += sx
            y += sy
            row_idx += 1

    c.save()
    buf.seek(0)
    return buf


def apply_watermark_to_pdf(
    input_path: str,
    output_path: str,
    config: WatermarkConfig,
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> str:
    """
    给指定 PDF 添加水印并导出。
    如果 config.rasterize 为 True，将在打上水印后调用整页图片化引擎，生成防篡改 PDF。
    """
    from rasterize_engine import rasterize_pdf_stream

    reader = PdfReader(input_path)
    total_pages = len(reader.pages)
    if total_pages == 0:
        raise ValueError(f"PDF 文件为空: {input_path}")

    writer = PdfWriter()

    # 水印页面缓存 (依据宽高不同缓存，避免每页重复生成)
    wm_cache = {}

    for i, page in enumerate(reader.pages):
        w = float(page.mediabox.width)
        h = float(page.mediabox.height)
        key = (round(w, 1), round(h, 1))

        if key not in wm_cache:
            wm_pdf_buf = create_watermark_layer(w, h, config)
            wm_reader = PdfReader(wm_pdf_buf)
            wm_cache[key] = wm_reader.pages[0]

        wm_page = wm_cache[key]

        if config.layer == "underlay":
            # 置于底部：在水印页上合并原页面
            new_page = pypdf.PageObject.create_blank_page(width=w, height=h)
            new_page.merge_page(wm_page)
            new_page.merge_page(page)
            writer.add_page(new_page)
        else:
            # 覆盖在上方 (默认)：原页上合并水印
            page.merge_page(wm_page)
            writer.add_page(page)

        if progress_callback:
            step_desc = "打水印中..." if not config.rasterize else "打水印并准备图片化..."
            progress_callback(i + 1, total_pages * (2 if config.rasterize else 1), step_desc)

    if not config.rasterize:
        # 直接输出矢量带水印 PDF
        with open(output_path, "wb") as f_out:
            writer.write(f_out)
        return output_path
    else:
        # 先输出至内存流，再调用图片化引擎
        temp_buf = io.BytesIO()
        writer.write(temp_buf)
        temp_buf.seek(0)

        def rasterize_progress(cur, tot, desc):
            if progress_callback:
                progress_callback(total_pages + cur, total_pages * 2, f"图片化防篡改渲染 ({cur}/{tot})...")

        rasterize_pdf_stream(
            temp_buf,
            output_path,
            dpi=config.dpi,
            quality=config.quality,
            progress_callback=rasterize_progress
        )
        return output_path


def render_preview_image(
    input_pdf_path: Optional[str],
    config: WatermarkConfig,
    page_index: int = 0,
    max_preview_size: Tuple[int, int] = (500, 680)
) -> Image.Image:
    """
    即时渲染指定 PDF 文件的第 page_index 页水印预览图。
    如果未选择 PDF 文件，则自动生成一张高质量的仿真 A4 样本文档进行预览。
    """
    if input_pdf_path and os.path.exists(input_pdf_path):
        try:
            reader = PdfReader(input_pdf_path)
            if len(reader.pages) > page_index:
                src_page = reader.pages[page_index]
                w = float(src_page.mediabox.width)
                h = float(src_page.mediabox.height)

                wm_buf = create_watermark_layer(w, h, config)
                wm_page = PdfReader(wm_buf).pages[0]

                merged_writer = PdfWriter()
                if config.layer == "underlay":
                    new_p = pypdf.PageObject.create_blank_page(width=w, height=h)
                    new_p.merge_page(wm_page)
                    new_p.merge_page(src_page)
                    merged_writer.add_page(new_p)
                else:
                    src_page.merge_page(wm_page)
                    merged_writer.add_page(src_page)

                out_buf = io.BytesIO()
                merged_writer.write(out_buf)
                out_buf.seek(0)

                doc = pdfium.PdfDocument(out_buf)
                scale = 1.2
                pil_img = doc[0].render(scale=scale).to_pil()
                pil_img.thumbnail(max_preview_size, Image.Resampling.LANCZOS)
                return pil_img
        except Exception as e:
            print(f"Error rendering preview from file: {e}")

    # 回退/默认：生成仿真 A4 样本文档
    w, h = 595.0, 842.0  # 标准 A4
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(w, h))

    # 绘制模拟文档外观：白色底、边框、标题、正文灰条
    c.setFillColor(colors.white)
    c.rect(0, 0, w, h, fill=1, stroke=0)

    # 模拟页眉与标题
    c.setFillColor(colors.HexColor("#2B3A42"))
    c.setFont("Helvetica-Bold", 18)
    c.drawString(60, 780, "CONFIDENTIAL REPORT / 业务合同示例文档")

    c.setFillColor(colors.HexColor("#7F8C8D"))
    c.setFont("Helvetica", 10)
    c.drawString(60, 760, "Document No: 2026-PDF-WM-001   Date: 2026-10-23   Page: 1/1")
    c.setStrokeColor(colors.HexColor("#BDC3C7"))
    c.setLineWidth(1)
    c.line(60, 750, 535, 750)

    # 模拟文本段落线条
    c.setFillColor(colors.HexColor("#ECF0F1"))
    y = 710
    while y > 150:
        c.rect(60, y, 475, 12, fill=1, stroke=0)
        y -= 22
        if y % 110 == 0:
            y -= 15  # 段落空行

    # 模拟印章/签名框
    c.setStrokeColor(colors.HexColor("#BDC3C7"))
    c.rect(340, 90, 180, 70, fill=0, stroke=1)
    c.setFillColor(colors.HexColor("#95A5A6"))
    c.setFont("Helvetica", 9)
    c.drawString(350, 145, "[ Authorized Signature ]")

    c.save()
    buf.seek(0)

    # 合并水印
    sample_page = PdfReader(buf).pages[0]
    wm_buf = create_watermark_layer(w, h, config)
    wm_page = PdfReader(wm_buf).pages[0]

    merged_writer = PdfWriter()
    if config.layer == "underlay":
        new_p = pypdf.PageObject.create_blank_page(width=w, height=h)
        new_p.merge_page(wm_page)
        new_p.merge_page(sample_page)
        merged_writer.add_page(new_p)
    else:
        sample_page.merge_page(wm_page)
        merged_writer.add_page(sample_page)

    out_buf = io.BytesIO()
    merged_writer.write(out_buf)
    out_buf.seek(0)

    doc = pdfium.PdfDocument(out_buf)
    pil_img = doc[0].render(scale=1.2).to_pil()
    pil_img.thumbnail(max_preview_size, Image.Resampling.LANCZOS)
    return pil_img
