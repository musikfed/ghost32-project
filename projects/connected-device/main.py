import gc
import sys

try:
    from server import run
    run()
except Exception as exc:
    print("Fatal runtime error:", exc)
    try:
        sys.print_exception(exc)
    except Exception:
        pass
finally:
    gc.collect()
