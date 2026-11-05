# V1.7.2 Windows 便携版交付验证

已验证并发布的软件提交：`f63f140`。

- [完整便携版 ZIP](https://github.com/jkanmax-alt/-pdf-/releases/download/portable-v1.7.2-r5/ElectricalQuote_V1.7.2_Windows_x64_Portable.zip)
- [Windows 实际执行报告](https://github.com/jkanmax-alt/-pdf-/releases/download/portable-v1.7.2-r5/Windows_Portable_Test_Reports.zip)
- [构建、验证与发布运行](https://github.com/jkanmax-alt/-pdf-/actions/runs/41942959249)
- [下载校验值](https://github.com/jkanmax-alt/-pdf-/releases/download/portable-v1.7.2-r5/ElectricalQuote_V1.7.2_Windows_x64_Portable.zip.sha256)

ZIP 大小为 224,937,322 字节，包含完整 onedir 文件夹。SHA256：

```text
f692cc843c3523dfa27b6d83b61983b2578fa7554e8bd9686cd1075ee19c5bc0
```

## 实际通过的 Windows 检查

构建机与验证机为两台独立、全新 GitHub-hosted Windows Server 2022 x64 VM。验证机不运行源码或构建脚本，只下载并启动产出的 EXE；测试进程 PATH 限制为 Windows 系统目录，同时清除 PYTHONHOME、PYTHONPATH、TESSDATA_PREFIX 等变量。

首次解压到含中文及空格的目录，从另一工作目录启动：

- 内置 Tesseract 版本、eng/chi_sim/osd 列表和逐模型实际加载自检通过。
- `sys.frozen` 为真；PyMuPDF、pytesseract、Pillow、OpenCV、NumPy、openpyxl、tkinter 均从 `_internal` 导入。
- 实际 Tk GUI 启动、导入合成 PDF、自动分柜通过。
- 实际冻结程序后台 spawn 子进程完成 OCR，识别出合成图中全部 11 个独立的 16A/1P 断路器。
- 通过 GUI 导出 Excel，再用内置 openpyxl 重新读取明细及汇总工作表。

将完整软件文件夹移动至另一中文/空格目录后，从不同工作目录重复上述自检与完整流程，全部通过。四份自检/E2E 报告的 `ok` 均为 `true`。

验证边界：Windows runner 镜像的磁盘上仍可能预装 Python。本测试隔离其 PATH，验证冻结 EXE 的所有运行依赖来自软件文件夹；没有声称已从操作系统物理卸载 Python。未在同事实体电脑逐一手工验收。使用公开合成 PDF 完成功能验证，没有上传用户原始图纸或历史报价。

## 产物独立检查

重新下载公开发布的 ZIP 后，SHA256 与发布校验值相符，ZIP CRC 检查通过，包含 2,826 个归档条目。静态检查全部 206 个 EXE/DLL/PYD：均为 x64，未发现缺失的非系统 DLL；VC++ 的 MSVCP140、VCRUNTIME140 和 VCRUNTIME140_1 等均已在包内。

Tesseract 自身包含 51 个 x64 DLL、三种语言数据、原始通知/许可证及文件校验清单。原始安装器在提取前按 Microsoft winget 固定清单核验 SHA256。为修复原生中文路径访问，嵌入 UTF-8 活动代码页清单；修改前后代码与数据节哈希相同，原引擎及修改后引擎的哈希均记录于 BUNDLE-MANIFEST。

15 个识别与报价业务模块与 V1.7.2 基线 `0d6632f` 的 AST 对比一致，比较时仅排除 OCR 资源初始化导入/调用及定位函数的部署实现。电气识别和报价规则未修改。

支持 Windows 10 1903 及以上 / Windows 11 x64。请完整解压 ZIP，双击 `ElectricalQuoteV172.exe`，不要单独复制 EXE。
