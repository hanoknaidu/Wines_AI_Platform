"""Dev entrypoint: python -m wines_ai"""

from __future__ import annotations

import uvicorn

from .config import get_settings


def main() -> None:
    get_settings()
    # Single worker, deliberately: the SSE bus, the in-flight turn registry and the
    # seq allocator are in-process, and SQLite takes one writer.
    uvicorn.run("wines_ai.main:app", host="127.0.0.1", port=8010, workers=1, reload=False)


if __name__ == "__main__":
    main()
