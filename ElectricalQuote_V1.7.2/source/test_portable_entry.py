import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import portable_entry


class EntryTests(unittest.TestCase):
    def test_import_failure_is_reported_before_gui(self):
        with tempfile.TemporaryDirectory() as td:
            report=Path(td)/'space path'/'startup.json'
            with patch.dict(sys.modules,{'app_v16':None}):
                code=portable_entry.main(['--self-check','--self-check-output',str(report)])
            self.assertEqual(code,1)
            result=json.loads(report.read_text(encoding='utf-8'))
            self.assertFalse(result['ok'])
            self.assertEqual(result['stage'],'startup-import')
            self.assertIn('app_v16',result['error'])

    def test_success_keeps_cli_arguments_and_exit_code(self):
        args=[]
        fake=types.SimpleNamespace(main=lambda value:args.extend(value) or 0)
        with patch.dict(sys.modules,{'app_v16':fake}):
            self.assertEqual(portable_entry.main(['--self-check']),0)
        self.assertEqual(args,['--self-check'])


if __name__=='__main__':unittest.main()
