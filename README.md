# ElectricalQuote

电气 PDF 图纸中的元器件识别、数量核对与清单导出工具。

当前修复版：[ElectricalQuote V1.7.1](ElectricalQuote_V1.7.1/README_CN.txt)。Windows 使用方法：

1. 解压/进入 `ElectricalQuote_V1.7.1/source`，运行 `install_windows.bat` 安装 Python 依赖。
2. 安装 Tesseract OCR 并加入 PATH，然后运行 `start_windows.bat`。
3. 检测分柜、核对图框、识别器件，人工确认数量与规格后导出。

快速校验运行 `verify_windows.bat`；包含示例 PDF OCR 的完整校验运行 `verify_windows.bat --full`。

仓库不包含用户原始图纸或历史报价。实际 PDF 回归需要将原包中的三份 PDF 在本地放入 `ElectricalQuote_V1.7.1/samples/`；不使用图纸的针对性测试可在 `source` 目录运行 `python -m unittest discover -p "test_*fixes.py"`。

候选数量、已确认数量和数量未知记录分开统计。本项目仍是需要 Python 和 Tesseract 的源码包，复杂图纸识别结果需要人工核对。
