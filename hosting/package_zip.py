"""Package the GoDaddy app from an explicit source allowlist."""
import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "package.json", "hosting/server.mjs", "frontend/index.html",
    "frontend/package.json", "frontend/package-lock.json",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    destination = parser.parse_args().destination
    assets = [path for path in (ROOT / "frontend/src").rglob("*") if path.is_file()]
    with ZipFile(destination, "x", compression=ZIP_DEFLATED) as archive:
        for relative in FILES:
            archive.write(ROOT / relative, relative)
        for path in assets:
            relative = path.relative_to(ROOT)
            if not any(part.startswith(".") for part in relative.parts) and path.suffix in {
                ".js", ".jsx", ".css", ".svg", ".png", ".jpg", ".webp", ".woff2", ".json",
            }:
                archive.write(path, relative.as_posix())
    print(destination.resolve())


if __name__ == "__main__":
    main()
