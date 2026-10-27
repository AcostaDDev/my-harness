"""No target effects until the parent durably records the group and sends GO.

Uses an independent pipe so buffered prompt reads cannot consume the gate.
EOF (parent crash before GO) terminates without executing the target.
"""
import os
import sys


def main():
    fd = int(sys.argv[1])
    with os.fdopen(fd, "rb", buffering=0) as gate:
        if gate.read(1) != b"G":
            return 125
    os.execvpe(sys.argv[2], sys.argv[2:], os.environ)


if __name__ == "__main__":
    sys.exit(main())
