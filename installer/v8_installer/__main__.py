"""Private JSONL backend. The public installer is the Go binary."""
import sys


def main():
    if sys.argv[1:] != ["--rpc"]:
        raise SystemExit("Use archhelper-install (or archhelper-install --demo)")
    from .protocol import main as serve
    raise SystemExit(serve())


if __name__ == "__main__":
    main()
