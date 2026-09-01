"""Launch the dashboard: python -m app"""
import os

import uvicorn

from app.main import app


def main() -> None:
    # Cloud hosts inject PORT; bind all interfaces there.
    default_host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    host = os.environ.get("HOST", default_host)
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
