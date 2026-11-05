"""Small frozen entry point: capture startup import/DLL errors before Tk loads."""
import json
import multiprocessing
import os
from pathlib import Path
import sys
import traceback


def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    try:
        from app_v16 import main as app_main
        return app_main(args)
    except Exception:
        error=traceback.format_exc()
        base=Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) / 'ElectricalQuote'
        output=base / 'startup-error.json'
        for flag in ('--self-check-output','--report'):
            if flag in args and args.index(flag)+1<len(args):
                output=Path(args[args.index(flag)+1]).expanduser().resolve();break
        result=dict(ok=False,bundled=False,frozen=bool(getattr(sys,'frozen',False)),
                    executable=sys.executable,error=error,errors=[error],stage='startup-import')
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        if '--self-check' not in args and '--portable-smoke-test' not in args:
            message='启动失败，请完整解压便携版。诊断文件：'+str(output)
            if sys.platform=='win32':
                import ctypes
                ctypes.windll.user32.MessageBoxW(None,message,'ElectricalQuote 启动检查',0x10)
            elif sys.stderr is not None:
                print(message,file=sys.stderr)
        return 1


if __name__=='__main__':
    multiprocessing.freeze_support()
    sys.exit(main())
