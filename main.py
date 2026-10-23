"""
PDF 水印小工具 - 主程序入口 (main.py)
"""

import sys
import os

# 开启 Windows 高分屏 (High DPI) 缩放清晰度支持
if sys.platform.startswith("win"):
    try:
        import ctypes
        # 设置每显示器感知，消除 2K/4K 屏幕上的字体模糊
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

from ui_app import create_app


def main():
    root, app = create_app()
    # 居中显示窗口
    root.update_idletasks()
    width = 1200
    height = 840
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = max(0, (screen_width - width) // 2)
    y = max(0, (screen_height - height) // 2)
    root.geometry(f"{width}x{height}+{x}+{y}")

    root.mainloop()


if __name__ == "__main__":
    main()
