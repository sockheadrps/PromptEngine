from __future__ import annotations

import argparse
import os


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(prog="promptlibretto-studio")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = parser.parse_args()

    uvicorn.run("studio.main:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
