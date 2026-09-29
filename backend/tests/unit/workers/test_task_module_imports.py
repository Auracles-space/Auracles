"""Guard the Celery worker's startup imports against cycles.

A worker boots by importing every module in the Celery app's `include` list
before it consumes anything. A circular import there kills the worker on
startup — and ECS still reports the service healthy, because the container
process starts. The queue silently stops being processed while every other
signal stays green.

The API never sees it: it imports the same modules in a different order, so a
cycle fatal to the worker leaves the API serving normally. Nor does the rest of
this suite, because by the time any test touches a task module the interpreter
has already pulled most of the app in through some other path. This runs in a
subprocess so the import graph starts empty, exactly as the worker's does.
"""

from __future__ import annotations

import subprocess
import sys

BOOT_WORKER_IMPORTS = """
from app.workers.celery_app import create_celery_app

app = create_celery_app()
app.loader.import_default_modules()
print(len(app.conf.include))
"""


def test_celery_worker_imports_every_task_module() -> None:
    """The worker's full startup import must succeed from a cold interpreter.

    Calls Celery's own `import_default_modules`, rather than importing the list
    by hand, so this keeps testing the real boot path if that list or the
    loader changes.
    """
    result = subprocess.run(
        [sys.executable, "-c", BOOT_WORKER_IMPORTS],
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert result.returncode == 0, (
        "A Celery worker cannot boot: importing its task modules failed.\n"
        f"{result.stderr}"
    )
    assert int(result.stdout.strip()) > 0
