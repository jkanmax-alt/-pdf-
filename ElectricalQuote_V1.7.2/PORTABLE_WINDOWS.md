# ElectricalQuote V1.7.2 Windows 绿色便携版

## 同事使用

1. 将整个 ZIP 解压到有写入权限的本地目录。
2. 双击 `ElectricalQuoteV172.exe`。启动时界面会显示内置 OCR 引擎及语言数据的自检结果。
3. 导入 PDF，执行自动分柜、识别元器件，然后导出 Excel。

必须保留 EXE 旁边的整个 `_internal` 文件夹。无需安装 Python、Tesseract、语言包，亦无需设置系统 PATH。支持 Windows 10（1903 或更新版本）/11 x64；不支持 32 位 Windows。文档、PDF 和导出文件可以放在其他目录。绿色版以 EXE 所在位置查找资源，从快捷方式或其他工作目录启动也使用同一套内置 OCR。

```text
ElectricalQuoteV172/
  ElectricalQuoteV172.exe
  PORTABLE_WINDOWS.md
  PYTHON-DEPENDENCIES.json
  _internal/
    tesseract/
      tesseract.exe
      *.dll
      tessdata/
        eng.traineddata
        chi_sim.traineddata
        osd.traineddata
      doc/                         原始 LICENSE、AUTHORS、README
      third_party_licenses/        语言数据许可、来源和校验依据
      BUNDLE-MANIFEST.json          全部引擎文件的 SHA256 / DLL 导入清单
    source/                        本版本源代码、依赖清单和构建脚本
    third_party_licenses/
    ...                            Python、Tk、MuPDF、图像与 Excel 依赖
```

出现 OCR 自检错误时，请重新解压完整 ZIP 并保留错误信息。手工移动 EXE 或删除 `_internal` 内文件会造成运行失败。

## 可重复构建

构建机需要 Windows x64、Python 3.11 x64、7-Zip，以及访问 GitHub/PyPI 的 HTTPS 网络。上述工具只用于构建，使用者的电脑无需安装。

在项目根目录运行（PowerShell）：

```powershell
py -3.11 -m venv source/.venv
source/.venv/Scripts/python.exe -m pip install -r requirements-build-windows.txt
source/.venv/Scripts/python.exe tools/prepare_tesseract_windows.py --output vendor/tesseract
source/.venv/Scripts/python.exe -m PyInstaller --clean --noconfirm source/ElectricalQuote.spec
Compress-Archive -Path dist/ElectricalQuoteV172 -DestinationPath dist/ElectricalQuoteV172-Windows-x64-portable.zip -Force
```

也可以双击 `source/build_exe_windows.bat`。输出是完整 onedir 文件夹以及 ZIP。批处理会复用已验证的 `vendor/tesseract`；如准备步骤中途失败，请删除未完成的生成目录后重试。`vendor/`、下载缓存及二进制构建产物不提交 Git。

在已安装构建依赖的命令行中，项目可从任何当前目录构建；向 PyInstaller 传入此 spec 的绝对路径即可。默认 `dist` / `build` 位于调用命令时的工作目录。资源路径由 spec 和运行时的实际文件位置确定，不依赖工作目录。

### 引擎来源与验证

- Windows 引擎：UB Mannheim Tesseract `5.4.0.20240606` 的原始 GitHub release 安装器。构建脚本验证 SHA256 `c885fff6998e0608ba4bb8ab51436e1c6775c2bafc2559a19b423e18678b60c9`，该值来自 Microsoft `winget-pkgs` 固定快照 `c98039ecea945dca5b368233b4011c5de70ee6ed` 的公开清单。
- 语言数据：`tesseract-ocr/tessdata_fast` 的 `4.1.0` 对应提交 `65727574dfcd264acbb0c3e07860e4e9e9b22185`。`eng`、`chi_sim`、`osd` 各有固定 SHA256。
- 为支持含中文的解压路径，准备脚本只为 `tesseract.exe` 嵌入 Windows `activeCodePage=UTF-8` 清单（Win10 1903+）。原引擎未含清单；若上游已有清单则保留其原始设置。代码、只读常量和数据节的 SHA256 在修改前后必须一致。原安装器仍按原始 SHA256 验证；原 EXE、补丁后 EXE 的 SHA256、嵌入清单全文及来源记录在 `BUNDLE-MANIFEST.json` 和 `third_party_licenses/TESSERACT-UTF8-MANIFEST.json`。修改元数据后的 EXE 不沿用上游原始数字签名。DLL、语言模型及识别算法不修改。
- 安装器通过 7-Zip 提取，**不会运行安装程序、修改注册表或系统 PATH**。完整保留全部运行 DLL、文档、配置和上游许可；训练工具与安装器插件无需分发。
- 准备阶段逐个审计 EXE 和 DLL：要求为 x64，所有非 Windows 系统 DLL 导入都必须在引擎目录内满足；在 Windows 上还会限制 PATH 执行引擎版本及三语言可用性检查。
- 所有下载启用 HTTPS 证书校验；已有缓存仍须通过同一 SHA256 验证。固定来源、下载哈希、每个文件的哈希以及 DLL 闭包都记录在 `BUNDLE-MANIFEST.json`。

手工核验已生成引擎：

```powershell
source/.venv/Scripts/python.exe tools/prepare_tesseract_windows.py --verify-only
```

Python 包的原始分发元数据和许可证一并收集；Python 版本自带许可、Tcl/Tk 资源、引擎原始通知也随包保留。`PYTHON-DEPENDENCIES.json` 列出实际构建包版本和原始许可元数据。`_internal/source/` 提供应用代码和构建配方，未为用户的原有代码另行指定许可证。

## 验证与交付条件

仓库中的 `Windows portable EXE` 工作流在 `windows-2022` 构建，并在另一台全新的 Windows runner 上下载生成的 ZIP，解压到含中文及空格的路径，将 PATH 限制为 Windows 系统目录，清除 Python/OCR 环境变量，再从不同工作目录运行最终 EXE。

命令行自检（GUI 版 EXE 使用报告文件返回结果）：

```powershell
$p = Start-Process ./ElectricalQuoteV172.exe -ArgumentList '--self-check --self-check-output C:/Temp/ocr-status.json' -PassThru -Wait
if ($p.ExitCode -ne 0) { throw 'OCR 自检失败' }
$p = Start-Process ./ElectricalQuoteV172.exe -ArgumentList '--portable-smoke-test --report C:/Temp/portable-test.json' -PassThru -Wait
if ($p.ExitCode -ne 0) { throw '完整便携版检查失败' }
```

完整检查会创建公开的合成电气图 PDF，经实际 GUI 导入、分柜、后台识别和 Excel 导出路径进行验证，并核对依赖来自打包目录。报告与最终 ZIP 会作为 CI artifact 保存。GitHub runner 的磁盘上仍可能预装 Python；清空 PATH 证明运行不依赖这些工具，不能等同于已在物理未安装 Python 的电脑上完成测试。

Linux 上只能验证源码、下载 SHA256、提取内容和 PE/DLL 闭包，不能构建或冒称已测试真实 Windows EXE。以 Windows 工作流本次成功报告为实际交付依据。打包修复不改变电气识别算法、元件选型或报价规则。
