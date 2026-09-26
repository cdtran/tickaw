"""Trusted parser subprocess: file paths only, no database or S3 credentials."""
import json
import resource
import sys
from pathlib import Path


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024**2, 64 * 1024**2))
    from packages.data_engine.profiling import ProfileError, profile_csv

    source, parquet, output = map(Path, sys.argv[1:4])
    try:
        result = profile_csv(source, parquet, int(sys.argv[4]))
    except ProfileError as error:
        result = {"error_code": error.code, "error_message": str(error)}
    output.write_text(json.dumps(result, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    main()
