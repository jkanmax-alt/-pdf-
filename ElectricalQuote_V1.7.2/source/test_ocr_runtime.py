"""Deployment regressions: never let an installed OCR hide an incomplete ZIP."""
import contextlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import pytesseract
import ocr_runtime as runtime


class PortableRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ)
        self.env.start()
        self.addCleanup(self.env.stop)
        previous = (runtime._active_engine, pytesseract.pytesseract.tesseract_cmd,
                    pytesseract.pytesseract.subprocess)
        def restore():
            runtime._active_engine, pytesseract.pytesseract.tesseract_cmd, pytesseract.pytesseract.subprocess = previous
        self.addCleanup(restore)

    def bundle(self, directory=None, languages=('eng', 'chi_sim', 'osd')):
        directory = directory or self.root / '_internal' / 'tesseract'
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'tesseract.exe').write_bytes(b'fixture executable')
        data = directory / 'tessdata'
        data.mkdir()
        for language in languages:
            (data / (language + '.traineddata')).write_bytes(b'fixture language')
        return directory

    @contextlib.contextmanager
    def frozen(self, meipass=None):
        with patch.object(sys, 'frozen', True, create=True), \
             patch.object(sys, 'executable', str(self.root / 'ElectricalQuoteV172.exe')), \
             patch.object(sys, '_MEIPASS', str(meipass or self.root / '_internal'), create=True):
            yield

    def test_frozen_bundle_wins_over_path_from_different_cwd(self):
        bundle = self.bundle()
        foreign = self.root / 'elsewhere'
        foreign.mkdir()
        previous = Path.cwd()
        try:
            os.chdir(foreign)
            with self.frozen(), patch.object(runtime.shutil, 'which') as lookup:
                path = runtime.initialize_ocr()
                self.assertEqual(path, str((bundle / 'tesseract.exe').resolve()))
                self.assertEqual(pytesseract.pytesseract.tesseract_cmd, path)
                self.assertEqual(os.environ['TESSDATA_PREFIX'], str((bundle / 'tessdata').resolve()))
                self.assertEqual(os.environ['PATH'].split(os.pathsep)[0], str(bundle.resolve()))
                lookup.assert_not_called()
        finally:
            os.chdir(previous)

    def test_frozen_missing_bundle_refuses_installed_engine(self):
        with self.frozen(), patch.object(runtime.shutil, 'which', return_value='/usr/bin/tesseract') as lookup:
            result = runtime.self_check()
            self.assertFalse(result['ok'])
            self.assertTrue(result['bundled'])
            self.assertIn('内置 Tesseract 引擎缺失', result['errors'][0])
            self.assertTrue(Path(pytesseract.pytesseract.tesseract_cmd).is_absolute())
            lookup.assert_not_called()

    def test_incomplete_bundle_does_not_fall_back_in_source_mode(self):
        directory = self.root / 'incomplete'
        directory.mkdir()
        with patch.object(runtime, '_bundle_directories', return_value=[directory]), \
             patch.object(runtime.shutil, 'which') as lookup:
            with self.assertRaises(runtime.OCRRuntimeError):
                runtime.initialize_ocr()
            lookup.assert_not_called()

    def test_meipass_and_legacy_executable_adjacent_layouts(self):
        for name in ('extracted', 'legacy'):
            with self.subTest(layout=name):
                directory = self.root / name
                bundle = self.bundle(directory / 'tesseract')
                if name == 'extracted':
                    patches = self.frozen(directory)
                else:
                    patches = contextlib.ExitStack()
                    patches.enter_context(patch.object(sys, 'frozen', True, create=True))
                    patches.enter_context(patch.object(sys, 'executable', str(directory / 'app.exe')))
                    patches.enter_context(patch.object(sys, '_MEIPASS', str(self.root / 'unused'), create=True))
                with patches:
                    self.assertEqual(runtime.initialize_ocr(), str((bundle / 'tesseract.exe').resolve()))

    def test_source_vendor_layout_does_not_need_path_lookup(self):
        fake_source = self.root / 'source'
        fake_source.mkdir()
        bundle = self.bundle(self.root / 'vendor' / 'tesseract')
        with patch.object(runtime, '__file__', str(fake_source / 'ocr_runtime.py')), \
             patch.object(runtime.shutil, 'which') as lookup:
            self.assertEqual(runtime.initialize_ocr(), str((bundle / 'tesseract.exe').resolve()))
            lookup.assert_not_called()

    def test_missing_language_has_explicit_failure(self):
        self.bundle(languages=('eng', 'osd'))
        with self.frozen(), patch.object(runtime, '_engine_output', side_effect=['tesseract 5.4.0', 'List of available languages (2):\neng\nosd']), \
             patch.object(runtime, '_check_language'):
            result = runtime.self_check()
        self.assertFalse(result['ok'])
        self.assertTrue(any('chi_sim' in message for message in result['errors']))

    def test_corrupt_model_is_detected_even_when_listed(self):
        self.bundle()
        with self.frozen(), patch.object(runtime, '_engine_output', side_effect=['tesseract 5.4.0', 'List of available languages (3):\nchi_sim\neng\nosd']), \
             patch.object(runtime, '_check_language', side_effect=runtime.OCRRuntimeError('corrupt traineddata')):
            result = runtime.self_check()
        self.assertFalse(result['ok'])
        self.assertIn('corrupt traineddata', result['errors'])

    def test_unloadable_engine_reports_failure_without_path_fallback(self):
        self.bundle()
        with self.frozen(), patch.object(runtime, '_engine_output', side_effect=OSError('missing DLL')), \
             patch.object(runtime.shutil, 'which') as lookup:
            result = runtime.self_check()
        self.assertFalse(result['ok'])
        self.assertIn('missing DLL', result['errors'][0])
        lookup.assert_not_called()

    def test_child_path_removes_python_dll_dir_without_editing_parent(self):
        bundle = self.bundle()
        with self.frozen():
            runtime.initialize_ocr()
            os.environ['PATH'] = os.pathsep.join([str(self.root / '_internal'), str(bundle), '/system-bin'])
            parent_path = os.environ['PATH']
            child = runtime._child_environment()
            self.assertEqual(child['PATH'].split(os.pathsep), [str(bundle.resolve()), '/system-bin'])
            self.assertEqual(os.environ['PATH'], parent_path)

    def test_child_path_removes_short_name_aliases_of_python_and_ocr_dirs(self):
        bundle = self.bundle()
        short_python = str(self.root / 'PYTHON~1')
        short_ocr = str(self.root / 'OCR~1')
        original_realpath = os.path.realpath
        aliases = {short_python: str((self.root / '_internal').resolve()),
                   short_ocr: str(bundle.resolve())}
        def realpath_with_windows_aliases(path, *args, **kwargs):
            return aliases.get(os.fspath(path), original_realpath(path, *args, **kwargs))
        with self.frozen():
            runtime.initialize_ocr()
            os.environ['PATH'] = os.pathsep.join([short_python, short_ocr, '/system-bin'])
            parent_path = os.environ['PATH']
            with patch.object(runtime.os.path, 'realpath', side_effect=realpath_with_windows_aliases):
                child = runtime._child_environment()
            self.assertEqual(child['PATH'].split(os.pathsep), [str(bundle.resolve()), '/system-bin'])
            self.assertEqual(os.environ['PATH'], parent_path)

    def test_windows_dll_directory_is_restored_when_child_launch_fails(self):
        original = str(self.root / '_internal')
        def get_directory(size, buffer):
            if buffer is not None:
                buffer.value = original
            return len(original)
        kernel = types.SimpleNamespace(GetDllDirectoryW=Mock(side_effect=get_directory),
                                       SetDllDirectoryW=Mock(return_value=1))
        with self.frozen(), patch.object(sys, 'platform', 'win32'), \
             patch.object(runtime.ctypes, 'WinDLL', create=True, return_value=kernel), \
             patch.object(runtime.subprocess, 'Popen', side_effect=OSError('cannot start')):
            with self.assertRaisesRegex(OSError, 'cannot start'):
                runtime._spawn_clean(['fixture.exe'])
        self.assertEqual(kernel.SetDllDirectoryW.call_args_list[0].args, (None,))
        self.assertEqual(kernel.SetDllDirectoryW.call_args_list[-1].args, (original,))

    def test_pytesseract_proxy_does_not_patch_python_subprocess(self):
        original = subprocess.Popen
        with patch.object(runtime, '_bundle_directories', return_value=[]):
            runtime.initialize_ocr()
        self.assertIs(subprocess.Popen, original)
        self.assertIsNot(pytesseract.pytesseract.subprocess, subprocess)

    def test_version_and_language_helpers_also_use_clean_process_launch(self):
        proxy = runtime._OCRSubprocess()
        for helper in ('check_output', 'run'):
            with self.subTest(helper=helper), patch.object(runtime, '_spawn_clean') as launch:
                process = launch.return_value.__enter__.return_value
                process.communicate.return_value = (b'tesseract 5.4.0', None)
                process.poll.return_value = 0
                process.args = ['fixture.exe', '--version']
                result = getattr(proxy, helper)(process.args)
                launch.assert_called_once()
                output = result if helper == 'check_output' else result.stdout
                self.assertEqual(output, b'tesseract 5.4.0')

    def test_frozen_cache_is_writable_user_data_outside_bundle(self):
        local = self.root / 'user-data'
        with self.frozen(), patch.dict(os.environ, {'LOCALAPPDATA': str(local)}):
            cache = runtime.writable_cache_dir()
            self.assertTrue(cache.is_relative_to(local.resolve()))
            self.assertFalse(cache.is_relative_to((self.root / '_internal').resolve()))

    def test_windowed_self_check_writes_json_with_no_stdout_or_tk(self):
        import app_v16
        report = self.root / 'reports' / 'self-check.json'
        result = dict(ok=True, bundled=True, engine_path='engine', tessdata_path='data',
                      version='tesseract 5.4.0', languages=['eng', 'chi_sim', 'osd'], errors=[])
        with patch.object(app_v16, 'self_check', return_value=result), \
             patch.object(sys, 'stdout', None), patch.object(app_v16.tk, 'Tk') as tk:
            code = app_v16.main(['--self-check', '--self-check-output', str(report)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(report.read_text(encoding='utf8')), result)
        tk.assert_not_called()

    def test_cli_smoke_entry_passes_absolute_report_and_returns_failure(self):
        import app_v16
        module = types.ModuleType('portable_smoke_test')
        module.main = Mock(return_value=1)
        report = self.root / 'smoke.json'
        with patch.dict(sys.modules, {'portable_smoke_test': module}), \
             patch.object(app_v16.tk, 'Tk') as tk:
            code = app_v16.main(['--portable-smoke-test', '--report', str(report)])
        self.assertEqual(code, 1)
        module.main.assert_called_once_with(report.resolve())
        tk.assert_not_called()

    @unittest.skipUnless(shutil.which('tesseract'), 'development Tesseract not available')
    def test_real_development_engine_load_and_ocr(self):
        from PIL import Image, ImageDraw, ImageFont
        with patch.object(runtime, '_bundle_directories', return_value=[]):
            result = runtime.self_check(required_languages=('eng',))
            self.assertTrue(result['ok'], result['errors'])
            self.assertIn('eng', result['languages'])
            image = Image.new('RGB', (550, 110), 'white')
            draw = ImageDraw.Draw(image)
            font_file = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
            font = ImageFont.truetype(str(font_file), 48) if font_file.is_file() else ImageFont.load_default(size=48)
            draw.text((20, 15), 'MCB 32A 3P', fill='black', font=font)
            text = pytesseract.image_to_string(image, lang='eng', config='--psm 7')
            self.assertIn('MCB', text)
            self.assertIn('32A', text)


if __name__ == '__main__':
    unittest.main()
