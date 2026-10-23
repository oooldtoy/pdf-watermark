"""
PDF 整页图片化防篡改引擎 (rasterize_engine.py)
利用 pypdfium2 高清栅格化渲染各页面为位图，并利用 Pillow 重新封装为纯图片型 PDF。
彻底将水印与原页面内容熔合为像素，使任何常规 PDF 编辑器无法单独选中、编辑或删除水印。
"""

import io
import os
import gc
from typing import Optional, Callable, Union
from PIL import Image
import pypdfium2 as pdfium


def rasterize_pdf_stream(
    input_source: Union[str, io.BytesIO],
    output_path: str,
    dpi: int = 200,
    quality: int = 85,
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> str:
    """
    将输入的 PDF（路径或 BytesIO）整页渲染为位图图像，并重新封装导出为只读图片型 PDF。

    :param input_source: PDF 文件路径或 BytesIO 字节流
    :param output_path: 导出的目标 PDF 文件绝对路径
    :param dpi: 渲染分辨率 (推荐 150 快速，200 标准高保真，300 印刷级)
    :param quality: JPEG 压缩画质 (推荐 80-90，兼顾体积与清晰度)
    :param progress_callback: 进度回调 (当前页, 总页数, 描述)
    :return: output_path
    """
    # 确保输出目录存在
    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    # 加载 PDF 文档
    if isinstance(input_source, io.BytesIO):
        input_source.seek(0)
        doc = pdfium.PdfDocument(input_source)
    else:
        doc = pdfium.PdfDocument(input_source)

    total_pages = len(doc)
    if total_pages == 0:
        raise ValueError("输入 PDF 无任何页面")

    scale = max(0.5, float(dpi) / 72.0)
    rendered_images = []

    try:
        for idx in range(total_pages):
            if progress_callback:
                progress_callback(
                    idx + 1,
                    total_pages,
                    f"正在将第 {idx + 1}/{total_pages} 页栅格化为位图 (DPI: {dpi})..."
                )

            page = doc[idx]
            # 高保真渲染为 PIL Image
            pil_image = page.render(scale=scale).to_pil()
            # 确保色彩空间为 RGB 格式
            if pil_image.mode != "RGB":
                pil_image = pil_image.convert("RGB")

            rendered_images.append(pil_image)

        if progress_callback:
            progress_callback(total_pages, total_pages, "正在合成并保存图片型防篡改 PDF...")

        # 使用 Pillow 组装多页图片为 PDF
        first_img = rendered_images[0]
        other_imgs = rendered_images[1:] if len(rendered_images) > 1 else []

        first_img.save(
            output_path,
            format="PDF",
            save_all=True,
            append_images=other_imgs,
            resolution=float(dpi),
            quality=int(quality),
            optimize=True
        )

    finally:
        # 显式关闭并释放所有图片对象与内存
        for img in rendered_images:
            try:
                img.close()
            except Exception:
                pass
        rendered_images.clear()
        try:
            doc.close()
        except Exception:
            pass
        gc.collect()

    return output_path
