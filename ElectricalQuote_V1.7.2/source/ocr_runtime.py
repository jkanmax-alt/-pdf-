"""Locate portable OCR resources independently of the current working directory.

Only this module deals with deployment paths. Recognition and selection rules
remain in their original modules.
"""
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading


class OCRRuntimeError(RuntimeError):
    pass


_launch_lock = threading.RLock()
_active_engine = None


def _bundle_directories():
    executable_dir = Path(sys.executable).resolve().parent
    source_dir = Path(__file__).resolve().parent
    # PyInstaller 6 onedir is the distribution format. Also accept older layouts.
    candidates = [executable_dir / '_internal' / 'tesseract']
    if getattr(sys, '_MEIPASS', None):
        candidates.append(Path(sys._MEIPASS).resolve() / 'tesseract')
    candidates.append(executable_dir / 'tesseract')
    if not getattr(sys, 'frozen', False):
        candidates.extend((source_dir / 'vendor' / 'tesseract',
                           source_dir.parent / 'vendor' / 'tesseract'))
    return list(dict.fromkeys(candidates))


def _discover_engine():
    for directory in _bundle_directories():
        if directory.is_dir():
            engine = directory / 'tesseract.exe'
            if not engine.is_file() and (directory / 'tesseract').is_file():
                engine = directory / 'tesseract'
            # An incomplete bundle must never be hidden by an installed engine.
            return dict(bundled=True, engine_path=str(engine.resolve()),
                        tessdata_path=str((directory / 'tessdata').resolve()))
    if getattr(sys, 'frozen', False):
        directory = _bundle_directories()[0]
        return dict(bundled=True, engine_path=str(directory / 'tesseract.exe'),
                    tessdata_path=str(directory / 'tessdata'))
    candidates = [shutil.which('tesseract'),
                  r'C:\Program Files\Tesseract-OCR\tesseract.exe',
                  r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe']
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            engine = Path(candidate).resolve()
            data = engine.parent / 'tessdata'
            return dict(bundled=False, engine_path=str(engine),
                        tessdata_path=str(data) if data.is_dir() else None)
    return dict(bundled=False, engine_path=None, tessdata_path=None)


def _child_environment(env=None):
    """Keep Tesseract's DLLs first and remove PyInstaller's Python DLL paths."""
    result = dict(os.environ if env is None else env)
    state = _active_engine or {}
    engine = state.get('engine_path')
    if not engine:
        return result
    engine_dir = str(Path(engine).parent)
    polluted = set()
    if getattr(sys, 'frozen', False):
        polluted.add(os.path.normcase(str(Path(sys.executable).resolve().parent / '_internal')))
        if getattr(sys, '_MEIPASS', None):
            polluted.add(os.path.normcase(str(Path(sys._MEIPASS).resolve())))
    entries = [p for p in result.get('PATH', '').split(os.pathsep)
               if p and os.path.normcase(os.path.abspath(p)) not in polluted
               and os.path.normcase(os.path.abspath(p)) != os.path.normcase(engine_dir)]
    result['PATH'] = os.pathsep.join([engine_dir] + entries)
    if state.get('tessdata_path'):
        result['TESSDATA_PREFIX'] = state['tessdata_path']
    return result


def _spawn_clean(*args, **kwargs):
    """Sanitize only the OCR child; restore the parent's DLL setting at once.

    PyInstaller sets SetDllDirectoryW for Python's bundled extensions. Windows
    propagates that setting to children, where it can select incompatible DLLs.
    The launch lock covers the brief save/clear/CreateProcess/restore sequence;
    Python retains its original DLL search setting while OCR is running.
    """
    kwargs['env'] = _child_environment(kwargs.get('env'))
    if sys.platform == 'win32':
        kwargs['creationflags'] = kwargs.get('creationflags', 0) | getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    if sys.platform != 'win32' or not getattr(sys, 'frozen', False):
        return subprocess.Popen(*args, **kwargs)
    with _launch_lock:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        get_directory = kernel.GetDllDirectoryW
        get_directory.argtypes = [ctypes.c_ulong, ctypes.c_wchar_p]
        get_directory.restype = ctypes.c_ulong
        set_directory = kernel.SetDllDirectoryW
        set_directory.argtypes = [ctypes.c_wchar_p]
        set_directory.restype = ctypes.c_int
        length = get_directory(0, None)
        previous = ctypes.create_unicode_buffer(length + 1)
        get_directory(len(previous), previous)
        if not set_directory(None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return subprocess.Popen(*args, **kwargs)
        finally:
            if not set_directory(previous.value or None):
                raise ctypes.WinError(ctypes.get_last_error())


def _run_clean(*popenargs, input=None, capture_output=False, timeout=None, check=False, **kwargs):
    """The subprocess.run interface, with OCR's sanitized process creation."""
    if input is not None:
        if kwargs.get('stdin') is not None:
            raise ValueError('stdin and input arguments may not both be used')
        kwargs['stdin'] = subprocess.PIPE
    if capture_output:
        if kwargs.get('stdout') is not None or kwargs.get('stderr') is not None:
            raise ValueError('stdout and stderr may not be used with capture_output')
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    with _spawn_clean(*popenargs, **kwargs) as process:
        try:
            stdout, stderr = process.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            process.kill()
            error.stdout, error.stderr = process.communicate()
            raise
        except BaseException:
            process.kill()
            raise
        returncode = process.poll()
        if check and returncode:
            raise subprocess.CalledProcessError(returncode, process.args, output=stdout, stderr=stderr)
        return subprocess.CompletedProcess(process.args, returncode, stdout, stderr)


def _check_output_clean(*popenargs, timeout=None, **kwargs):
    if 'stdout' in kwargs or 'check' in kwargs:
        raise ValueError('stdout and check arguments are not allowed in check_output')
    if 'input' in kwargs and kwargs['input'] is None:
        kwargs['input'] = '' if kwargs.get('text') or kwargs.get('universal_newlines') or kwargs.get('encoding') else b''
    return _run_clean(*popenargs, stdout=subprocess.PIPE, timeout=timeout, check=True, **kwargs).stdout


class _OCRSubprocess:
    """A pytesseract-local proxy, without patching Python's subprocess module."""
    Popen = staticmethod(_spawn_clean)
    run = staticmethod(_run_clean)
    check_output = staticmethod(_check_output_clean)

    def __getattr__(self, name):
        return getattr(subprocess, name)


def initialize_ocr():
    """Configure pytesseract before any OCR call; return the absolute engine path.

    No external command or OCR is run here, so repeated calls and spawned
    recognition workers use exactly the same setup without startup overhead.
    """
    global _active_engine
    import pytesseract
    state = _discover_engine()
    _active_engine = state
    engine = state['engine_path']
    # Even a missing bundled executable is absolute: never retain 'tesseract'
    # as a command that could accidentally resolve through the system PATH.
    pytesseract.pytesseract.tesseract_cmd = engine or 'tesseract'
    pytesseract.pytesseract.subprocess = _OCRSubprocess()
    if state['bundled']:
        os.environ['TESSDATA_PREFIX'] = state['tessdata_path']
        engine_dir = str(Path(engine).parent)
        entries = [p for p in os.environ.get('PATH', '').split(os.pathsep)
                   if p and os.path.normcase(os.path.abspath(p)) != os.path.normcase(engine_dir)]
        os.environ['PATH'] = os.pathsep.join([engine_dir] + entries)
    if not engine or not Path(engine).is_file():
        if state['bundled']:
            raise OCRRuntimeError('内置 Tesseract 引擎缺失：' + str(engine) +
                                  '。请完整解压绿色版文件夹，不能只复制 EXE。')
        return None
    return engine


def locate_tesseract():
    return initialize_ocr()


def _engine_output(engine, option):
    kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                  text=True, encoding='utf-8', errors='replace')
    if sys.platform == 'win32':
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    process = _spawn_clean([engine, option], **kwargs)
    try:
        output, _ = process.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise OCRRuntimeError('Tesseract 自检超时：' + option)
    if process.returncode:
        raise OCRRuntimeError('Tesseract ' + option + ' 失败（退出码 ' +
                              str(process.returncode) + '）：' + output.strip())
    return output.strip()


def _check_language(engine, language):
    # Listing languages only checks filenames. Initializing OCR on a blank PGM
    # also detects corrupt/incompatible traineddata without needing GUI fonts.
    kwargs = dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if sys.platform == 'win32':
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    process = _spawn_clean([engine, 'stdin', 'stdout', '-l', language, '--psm', '6'], **kwargs)
    try:
        _, diagnostic = process.communicate(b'P5\n50 50\n255\n' + b'\xff' * 2500, timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise OCRRuntimeError('语言数据加载超时：' + language)
    if process.returncode:
        raise OCRRuntimeError('语言数据无法加载：' + language + '；' +
                              diagnostic.decode('utf-8', errors='replace').strip())


def self_check(required_languages=('eng', 'chi_sim', 'osd')):
    """Actually launch the engine and verify that required language data loads."""
    state = _discover_engine()
    result = dict(ok=False, **state, version='', languages=[], errors=[])
    try:
        engine = initialize_ocr()
        if not engine:
            raise OCRRuntimeError('找不到 Tesseract OCR 引擎。绿色版应包含 _internal/tesseract。')
        if state['bundled']:
            data = Path(state['tessdata_path'])
            if not data.is_dir():
                result['errors'].append('内置 tessdata 语言数据目录缺失：' + str(data))
            for language in required_languages:
                language_file = data / (language + '.traineddata')
                if not language_file.is_file() or language_file.stat().st_size == 0:
                    result['errors'].append('语言数据缺失或为空：' + str(language_file))
        version = _engine_output(engine, '--version')
        result['version'] = version.splitlines()[0] if version else ''
        listing = _engine_output(engine, '--list-langs')
        lines = listing.splitlines()
        # Tesseract prints the actual tessdata directory in the first line.
        if not result['tessdata_path']:
            import re
            match = re.search(r'"([^"]+)"', listing)
            if match:
                result['tessdata_path'] = str(Path(match.group(1)).resolve())
        result['languages'] = sorted(line.strip() for line in lines
                                     if line.strip() and not line.startswith('List of available languages')
                                     and not line.startswith(('Error', 'Warning', 'Please ')))
        missing = sorted(set(required_languages) - set(result['languages']))
        if missing:
            result['errors'].append('OCR 引擎无法使用语言数据：' + ', '.join(missing))
        for language in required_languages:
            if language in result['languages']:
                try:
                    _check_language(engine, language)
                except Exception as error:
                    result['errors'].append(str(error))
    except Exception as error:
        result['errors'].append(str(error))
    result['ok'] = not result['errors']
    return result


def writable_cache_dir():
    """Keep generated recognition caches outside a frozen installation."""
    if getattr(sys, 'frozen', False):
        base = os.environ.get('LOCALAPPDATA')
        if not base:
            base = str(Path.home() / 'AppData' / 'Local') if os.name == 'nt' else str(Path.home() / '.cache')
        return Path(base).expanduser().resolve() / 'ElectricalQuote' / 'V1.7.2' / 'cache'
    return Path(__file__).resolve().parent / 'cache'
