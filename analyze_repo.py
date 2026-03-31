#!/usr/bin/env python3
"""
analyze_repo.py — Multi-language repo analyzer (dispatcher).
Detects languages present in a repo and delegates to per-language plugins.

Usage: python analyze_repo.py ./myapp [--output repo_graph.json]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from analyzers import (
    python_analyzer,
    js_analyzer,
    css_analyzer,
    go_analyzer,
    ruby_analyzer,
    rust_analyzer,
    java_analyzer,
    php_analyzer,
    docker_analyzer,
    ci_analyzer,
    schema_analyzer,
)

_SKIP = {
    "__pycache__", ".venv", "venv", "env", ".git",
    "node_modules", "dist", "build", ".next",
    "target", "vendor", ".bundle",
}


def _has_files(root: Path, patterns: list, skip_dirs: set = None) -> bool:
    skip = skip_dirs or _SKIP
    return any(not any(part in skip for part in p.parts) for p in root.rglob(patterns[0]))


def _any_match(root: Path, globs: list) -> bool:
    return any(
        p for g in globs for p in root.rglob(g)
        if not any(part in _SKIP for part in p.parts)
    )


def detect_languages(root: Path) -> list:
    langs = []

    if _any_match(root, ["*.py"]):
        langs.append("python")

    js_signals = ["*.js", "*.ts", "*.jsx", "*.tsx", "*.mjs", "*.vue"]
    if (root / "package.json").exists() or _any_match(root, js_signals):
        langs.append("javascript")

    css_signals = ["*.css", "*.scss", "*.sass", "*.less", "*.styl"]
    if _any_match(root, css_signals):
        langs.append("css")

    if (root / "go.mod").exists() or _any_match(root, ["*.go"]):
        langs.append("go")

    if (root / "Gemfile").exists() or _any_match(root, ["*.rb"]):
        langs.append("ruby")

    if (root / "Cargo.toml").exists() or _any_match(root, ["*.rs"]):
        langs.append("rust")

    if _any_match(root, ["*.java", "*.kt", "*.kts"]):
        langs.append("java")

    if (root / "composer.json").exists() or _any_match(root, ["*.php"]):
        langs.append("php")

    # Infrastructure
    compose_names = ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]
    if any((root / n).exists() for n in compose_names) or _any_match(root, ["Dockerfile*"]):
        langs.append("docker")

    if (root / ".github" / "workflows").exists() or \
       (root / ".gitlab-ci.yml").exists() or (root / ".gitlab-ci.yaml").exists():
        langs.append("ci")

    if _any_match(root, ["*.sql", "*.prisma"]):
        langs.append("schema")

    return langs


def merge_links(target: dict, source: dict) -> None:
    for k, v in source.items():
        target[k] = target.get(k, 0) + v


_INFRA_TYPES = {"service", "pipeline", "database"}

def link_kind(s_type: str, t_type: str) -> str:
    if s_type == "style" or t_type == "style":
        return "styles"
    if s_type in _INFRA_TYPES or t_type in _INFRA_TYPES:
        return "depends"
    if s_type in {"component", "route"} and t_type in {"component", "route"}:
        return "renders"
    return "imports"


# Maps language id → analyzer module
_ANALYZERS = {
    "python":     python_analyzer,
    "javascript": js_analyzer,
    "css":        css_analyzer,
    "go":         go_analyzer,
    "ruby":       ruby_analyzer,
    "rust":       rust_analyzer,
    "java":       java_analyzer,
    "php":        php_analyzer,
    "docker":     docker_analyzer,
    "ci":         ci_analyzer,
    "schema":     schema_analyzer,
}


def analyze(root_path: str) -> dict:
    root = Path(root_path).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Path not found: {root}")

    langs = detect_languages(root)
    if not langs:
        print(f"Warning: no supported languages detected in {root}", file=sys.stderr)

    group_map    = {}
    all_nodes    = []
    all_links    = {}
    ext_seen     = set()
    total_files  = 0
    total_loc    = 0
    meta_extra   = {}

    def add_results(nodes, ext_nodes, links_map, meta):
        nonlocal total_files, total_loc
        all_nodes.extend(nodes)
        for en in ext_nodes:
            if en["id"] not in ext_seen:
                all_nodes.append(en)
                ext_seen.add(en["id"])
        merge_links(all_links, links_map)
        total_files += meta.get("total_files", 0)
        total_loc   += meta.get("total_loc", 0)
        for key in ("framework", "packageManager"):
            if meta.get(key):
                meta_extra.setdefault(key, meta[key])

    for lang in langs:
        analyzer = _ANALYZERS.get(lang)
        if analyzer:
            try:
                result = analyzer.analyze(root, group_map)
                add_results(*result)
            except Exception as e:
                print(f"Warning: {lang} analyzer failed: {e}", file=sys.stderr)

    # Build links with semantic kind annotation
    node_type_map = {n["id"]: n.get("type", "module") for n in all_nodes}
    links = [
        {
            "source": s,
            "target": t,
            "weight": w,
            "kind":   link_kind(node_type_map.get(s, "module"), node_type_map.get(t, "module")),
        }
        for (s, t), w in all_links.items()
    ]

    return {
        "meta": {
            "root":        str(root.name) + "/",
            "total_files": total_files,
            "total_loc":   total_loc,
            "languages":   langs,
            **meta_extra,
        },
        "nodes": all_nodes,
        "links": links,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Analyze a repo and emit repo_graph.json")
    parser.add_argument("repo", help="Path to repo root")
    parser.add_argument("--output", default="repo_graph.json", help="Output JSON file")
    args = parser.parse_args()

    print(f"Analyzing {args.repo} …", file=sys.stderr)
    data = analyze(args.repo)
    out  = Path(args.output)
    out.write_text(json.dumps(data, indent=2))
    meta      = data["meta"]
    langs_str = ", ".join(meta.get("languages", ["unknown"]))
    print(
        f"Done. {meta['total_files']} files, {meta['total_loc']} LOC "
        f"[{langs_str}] → {out}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
