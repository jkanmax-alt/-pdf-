# ElectricalQuote

电气 PDF 图纸中的元器件识别、数量核对与清单导出工具。

当前版本：ElectricalQuote V1.7.2。

## Windows 绿色便携版

在 [Releases](https://github.com/jkanmax-alt/-pdf-/releases) 下载名称为 `ElectricalQuote_V1.7.2_Windows_x64_Portable.zip` 的完整程序包，解压后双击 `ElectricalQuoteV172.exe`。必须保留旁边整个 `_internal` 文件夹。使用者无需安装 Python、Tesseract 或语言数据，也无需设置 PATH。

支持 Windows 10 1903 及以上、Windows 11 x64。包含 OCR 引擎、运行 DLL、eng/chi_sim/osd 数据、启动自检及 Excel 依赖。操作、构建、依赖来源和测试边界见 [便携版说明](ElectricalQuote_V1.7.2/PORTABLE_WINDOWS.md)。每次发布附测试报告和 SHA256。仓库的 Code → Download ZIP 提供源码，完整 EXE 使用上述 Release 附件。

[下载已验证的完整便携版](https://github.com/jkanmax-alt/-pdf-/releases/download/portable-v1.7.2-r5/ElectricalQuote_V1.7.2_Windows_x64_Portable.zip) · [实际验证记录](docs/portable-windows-validation.md)

## 源码开发

[ElectricalQuote V1.7.2 源码说明](ElectricalQuote_V1.7.2/README_CN.txt)。源码运行方法：

1. 解压/进入 `ElectricalQuote_V1.7.2/source`，运行 `install_windows.bat` 安装 Python 依赖。
2. 安装 Tesseract OCR 并加入 PATH，然后运行 `start_windows.bat`。
3. 检测分柜、核对图框、识别器件，人工确认数量与规格后导出。

快速校验运行 `verify_windows.bat`；包含示例 PDF OCR 的完整校验运行 `verify_windows.bat --full`。

仓库不包含用户原始图纸或历史报价。实际 PDF 回归需要将原包中的三份 PDF 在本地放入 `ElectricalQuote_V1.7.2/samples/`；不使用图纸的针对性测试可在 `source` 目录运行 `python -m unittest discover -p "test_*fixes.py"`。

候选数量、已确认数量和数量未知记录分开统计。源码开发环境需要 Python 和 Tesseract；便携版已包含运行依赖。复杂图纸识别结果需要人工核对。
