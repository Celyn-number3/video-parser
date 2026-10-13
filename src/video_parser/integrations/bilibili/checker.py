"""Read-only validation of this downloader's JSON/SRT/MD output triplets."""

import argparse
import json
import math
from pathlib import Path


def check(json_path):
    path = Path(json_path).resolve()
    result = {"json": str(path), "ok": False, "lines": None, "files": [], "errors": []}
    if path.parent.name != "_json" or path.suffix.lower() != ".json":
        result["errors"].append("Expected a subtitle .json file under an _json directory")
        return result
    paths = [path, path.parent.parent / "_srt" / f"{path.stem}.srt",
             path.parent.parent / "_md" / f"{path.stem}.md"]
    for output in paths:
        try:
            if not output.is_file() or output.stat().st_size == 0:
                result["errors"].append(f"Missing or empty file: {output}")
            elif not output.read_text(encoding="utf-8").strip():
                result["errors"].append(f"Blank file: {output}")
            else:
                result["files"].append(str(output))
        except (OSError, UnicodeError) as exc:
            result["errors"].append(f"Cannot read {output}: {exc}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        body = data.get("body") if isinstance(data, dict) else None
        if not isinstance(body, list) or not body:
            raise ValueError("Subtitle body must be a nonempty list")
        result["lines"] = len(body)
        for index, row in enumerate(body, 1):
            if not isinstance(row, dict) or not isinstance(row.get("content"), str):
                raise ValueError(f"Row {index}: invalid subtitle content")
            times = [row.get("from"), row.get("to")]
            if not all(type(t) in (int, float) and math.isfinite(t) for t in times):
                raise ValueError(f"Row {index}: invalid time fields")
            if not 0 <= times[0] <= times[1]:
                raise ValueError(f"Row {index}: invalid time range")
        if not any(row["content"].strip() for row in body):
            raise ValueError("All subtitle content is blank")
    except (OSError, UnicodeError, ValueError, OverflowError) as exc:
        result["errors"].append(f"Invalid subtitle JSON: {exc}")
    result["ok"] = not result["errors"]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json_paths", nargs="+", help="Exact target subtitle JSON paths; no recursive scan")
    args = parser.parse_args()
    results = [check(path) for path in args.json_paths]
    print(json.dumps({"ok": all(item["ok"] for item in results), "results": results},
                     ensure_ascii=False, indent=2))
    return 0 if all(item["ok"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
