"""Isolated development harness for the integrated Question Workbench station."""
from __future__ import annotations

import argparse

from ingestion_v2.workbench_server import QUESTION_WORKBENCH_DIRECTORY, WorkbenchHandler


class QuestionWorkbenchHandler(WorkbenchHandler):
    """Serve the Question UI at / while retaining the unified API implementation."""

    def __init__(self, *args, **kwargs):
        super(WorkbenchHandler, self).__init__(
            *args, directory=str(QUESTION_WORKBENCH_DIRECTORY), **kwargs
        )


def main() -> None:
    from http.server import ThreadingHTTPServer

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), QuestionWorkbenchHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
