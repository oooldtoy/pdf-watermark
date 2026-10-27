# PDF 水印助手

一个基于 Python/Tkinter 的 Windows PDF 批量加水印工具。

## 功能

- 批量选择或拖拽导入 PDF，也支持导入文件夹中的 PDF。
- 支持平铺水印和居中单个水印。
- 可调整文字、字体、字号、颜色、透明度、旋转角度和间距。
- 支持实时预览和多页切换。
- 支持两种输出模式：
  - **矢量水印**：文件体积较小，原 PDF 文字仍可选中复制。
  - **整页图片化**：将页面和水印合成为图片，适合降低水印被单独编辑或移除的风险。
- 支持批量处理、进度显示、自定义输出目录和文件名后缀。
- Windows 中文字体自动检测，并支持保存常用设置。

## 使用

### 运行环境

- Windows
- Python 3.8+
- 依赖：`pypdf`、`pypdfium2`、`reportlab`、`Pillow`
- 可选依赖：`tkinterdnd2`，用于文件拖拽导入

安装依赖：

```powershell
pip install pypdf pypdfium2 reportlab pillow tkinterdnd2
```

### 启动

```powershell
python main.py
```

启动后添加 PDF，设置水印参数，确认预览效果，然后点击“开始批量生成水印 PDF”。

## 打包 EXE

本地打包前安装依赖：

```powershell
python -m pip install -r requirements.txt
```

执行打包：

```powershell
python -m PyInstaller --noconsole --onefile --clean --name "PDF水印助手" main.py
```

生成文件位于 `dist/PDF水印助手.exe`。

## 发布 GitHub Release

仓库包含 GitHub Actions 工作流 [`release.yml`](.github/workflows/release.yml)，会在推送版本标签后自动使用 Windows Runner 构建 EXE，并创建 GitHub Release。

```powershell
git add .
git commit -m "Prepare v1.0.0 release"
git push origin main
git tag v1.0.0
git push origin v1.0.0
```

也可以在 GitHub Actions 页面手动运行 `Build and Release Windows EXE`，并填写版本标签。发布完成后，`PDF水印助手.exe` 会作为 Release 附件提供下载。

## 项目结构

```text
pdf-watermark/
├── main.py              # 程序入口
├── ui_app.py            # 图形界面、预览和批量任务
├── watermark_engine.py  # 水印生成与 PDF 合并
├── rasterize_engine.py  # PDF 整页图片化
└── README.md            # 项目说明
```
