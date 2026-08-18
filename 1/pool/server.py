"""Pool coordinator entry point. Default :9100, override with POOL_PORT."""
import os

from pool.coordinator import make_coordinator
from pool.store import PoolStore
from shared.a2a import serve_blocking


def main() -> None:
    port = int(os.environ.get("POOL_PORT", "9100"))
    serve_blocking(make_coordinator(PoolStore()), host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
