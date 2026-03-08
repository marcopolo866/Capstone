#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


PATTERN_LAD = """3
1 2 1 2
1 2 0 2
1 2 0 1
"""

TARGET_LAD = """4
1 3 1 2 3
1 3 0 2 3
1 3 0 1 3
1 3 0 1 2
"""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(65536)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def resolve_binary(path: Path) -> Path:
    if path.is_file():
        return path
    if os.name == "nt":
        exe = Path(str(path) + ".exe")
        if exe.is_file():
            return exe
    raise FileNotFoundError(f"Missing binary: {path}")


def extract_solution_count(text: str) -> int | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None

    count_patterns = (
        re.compile(r"\bsolution[_\s-]*count\b\s*(?:=|:)?\s*(-?\d+)\b", re.IGNORECASE),
        re.compile(r"\b(?:solutions?|count)\b[^0-9-]*(-?\d+)\b", re.IGNORECASE),
        re.compile(r"\b(-?\d+)\s+solutions?\b", re.IGNORECASE),
    )
    for line in reversed(lines):
        for pattern in count_patterns:
            match = pattern.search(line)
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    continue

    int_line = re.compile(r"^-?\d+$")
    for line in reversed(lines):
        if int_line.match(line):
            try:
                return int(line)
            except ValueError:
                continue
    return None


def extract_vf3_count(text: str) -> int | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        if line.lower().startswith("solution"):
            continue
        m = re.match(r"^(-?\d+)(?:\s|$)", line)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return extract_solution_count(text)


def run_cmd(cmd: list[str], label: str, timeout_sec: int = 120) -> str:
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{label} timed out: {' '.join(cmd)}") from exc

    merged = "\n".join(
        part for part in (completed.stdout, completed.stderr) if part is not None
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{label} failed (exit {completed.returncode}):\n{merged.strip()}")
    return merged


def run_count(cmd: list[str], label: str) -> int:
    merged = run_cmd(cmd, label)
    parsed = extract_solution_count(merged)
    if parsed is None:
        raise RuntimeError(
            f"{label} output did not contain a parseable solution count:\n{merged.strip()}"
        )
    return parsed


def run_vf3_count(cmd: list[str], label: str) -> int:
    merged = run_cmd(cmd, label)
    parsed = extract_vf3_count(merged)
    if parsed is None:
        raise RuntimeError(
            f"{label} output did not contain a parseable count:\n{merged.strip()}"
        )
    return parsed


def run_generated_case(
    *,
    repo_root: Path,
    generator_script: Path,
    seed: int,
    n: int,
    k: int,
    density: float,
    baseline_binary: Path,
    chatgpt_binary: Path,
    gemini_binary: Path,
    vf3_binary: Path,
    tmpdir: Path,
) -> dict[str, int]:
    out_dir = tmpdir / f"generated_seed_{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)

    gen_cmd = [
        sys.executable,
        str(generator_script),
        "--algorithm",
        "subgraph",
        "--n",
        str(n),
        "--k",
        str(k),
        "--density",
        str(density),
        "--seed",
        str(seed),
        "--out-dir",
        str(out_dir),
    ]
    gen_out = run_cmd(gen_cmd, f"Generator seed={seed}")
    lines = [line.strip() for line in gen_out.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"Generator produced no output for seed={seed}.")
    parts = [p.strip() for p in lines[-1].split(",")]
    if len(parts) != 4:
        raise RuntimeError(
            f"Generator output parse error for seed={seed}. Expected 4 paths, got: {lines[-1]}"
        )
    lad_pattern, lad_target, vf_pattern, vf_target = [Path(p) for p in parts]

    baseline_count = run_count(
        [
            str(baseline_binary),
            "--count-solutions",
            "--format",
            "vertexlabelledlad",
            str(lad_pattern),
            str(lad_target),
        ],
        f"Glasgow baseline generated seed={seed}",
    )
    chatgpt_count = run_count(
        [str(chatgpt_binary), str(lad_pattern), str(lad_target)],
        f"Glasgow ChatGPT generated seed={seed}",
    )
    gemini_count = run_count(
        [str(gemini_binary), str(lad_pattern), str(lad_target)],
        f"Glasgow Gemini generated seed={seed}",
    )
    vf3_count = run_vf3_count(
        [str(vf3_binary), "-u", "-r", "0", "-e", str(vf_pattern), str(vf_target)],
        f"VF3 baseline generated seed={seed}",
    )

    return {
        "seed": seed,
        "baseline": baseline_count,
        "chatgpt": chatgpt_count,
        "gemini": gemini_count,
        "vf3": vf3_count,
    }


def parse_seed_list(raw: str) -> list[int]:
    out: list[int] = []
    for token in (raw or "").split(","):
        t = token.strip()
        if not t:
            continue
        out.append(int(t))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Check Glasgow baseline/ChatGPT/Gemini parity on deterministic LAD graphs, "
            "including generated subgraph cases."
        )
    )
    parser.add_argument(
        "--baseline-binary",
        default="baselines/glasgow-subgraph-solver/build/glasgow_subgraph_solver",
    )
    parser.add_argument("--chatgpt-binary", default="src/glasgow_chatgpt")
    parser.add_argument("--gemini-binary", default="src/glasgow_gemini")
    parser.add_argument("--vf3-binary", default="baselines/vf3lib/bin/vf3")
    parser.add_argument("--chatgpt-source", default="src/[CHATGPT] Glasgow.cpp")
    parser.add_argument("--gemini-source", default="src/[GEMINI] Glasgow.cpp")
    parser.add_argument("--generator-script", default="utilities/generate_graphs.py")
    parser.add_argument("--generated-seeds", default="803278420")
    parser.add_argument("--generated-n", type=int, default=100)
    parser.add_argument("--generated-k", type=int, default=10)
    parser.add_argument("--generated-density", type=float, default=0.07)
    parser.add_argument("--skip-generated", action="store_true")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    baseline_binary = resolve_binary((repo_root / args.baseline_binary).resolve())
    chatgpt_binary = resolve_binary((repo_root / args.chatgpt_binary).resolve())
    gemini_binary = resolve_binary((repo_root / args.gemini_binary).resolve())
    vf3_binary = resolve_binary((repo_root / args.vf3_binary).resolve())
    chatgpt_source = (repo_root / args.chatgpt_source).resolve()
    gemini_source = (repo_root / args.gemini_source).resolve()
    generator_script = (repo_root / args.generator_script).resolve()

    if not chatgpt_source.is_file() or not gemini_source.is_file():
        missing = [str(p) for p in (chatgpt_source, gemini_source) if not p.is_file()]
        raise FileNotFoundError("Missing source file(s): " + ", ".join(missing))
    if not generator_script.is_file() and not args.skip_generated:
        raise FileNotFoundError(f"Missing generator script: {generator_script}")

    chat_src_sha = sha256_file(chatgpt_source)
    gem_src_sha = sha256_file(gemini_source)
    if chat_src_sha == gem_src_sha:
        raise RuntimeError(
            "Glasgow LLM source files are identical (Option B requires separate .cpp implementations)."
        )

    chat_bin_sha = sha256_file(chatgpt_binary)
    gem_bin_sha = sha256_file(gemini_binary)
    baseline_bin_sha = sha256_file(baseline_binary)

    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="glasgow-parity-") as tmp:
        tmpdir = Path(tmp)

        pattern_path = tmpdir / "pattern.lad"
        target_path = tmpdir / "target.lad"
        pattern_path.write_text(PATTERN_LAD, encoding="utf-8")
        target_path.write_text(TARGET_LAD, encoding="utf-8")

        baseline_count = run_count(
            [
                str(baseline_binary),
                "--count-solutions",
                "--format",
                "vertexlabelledlad",
                str(pattern_path),
                str(target_path),
            ],
            "Glasgow baseline small",
        )
        chatgpt_count = run_count(
            [str(chatgpt_binary), str(pattern_path), str(target_path)],
            "Glasgow ChatGPT small",
        )
        gemini_count = run_count(
            [str(gemini_binary), str(pattern_path), str(target_path)],
            "Glasgow Gemini small",
        )

        if chatgpt_count != baseline_count:
            failures.append(
                f"small_case chatgpt mismatch: baseline={baseline_count}, chatgpt={chatgpt_count}"
            )
        if gemini_count != baseline_count:
            failures.append(
                f"small_case gemini mismatch: baseline={baseline_count}, gemini={gemini_count}"
            )

        generated_results: list[dict[str, int]] = []
        if not args.skip_generated:
            seeds = parse_seed_list(args.generated_seeds)
            if not seeds:
                raise RuntimeError("generated-seeds is empty while generated checks are enabled.")
            for seed in seeds:
                result = run_generated_case(
                    repo_root=repo_root,
                    generator_script=generator_script,
                    seed=seed,
                    n=args.generated_n,
                    k=args.generated_k,
                    density=args.generated_density,
                    baseline_binary=baseline_binary,
                    chatgpt_binary=chatgpt_binary,
                    gemini_binary=gemini_binary,
                    vf3_binary=vf3_binary,
                    tmpdir=tmpdir,
                )
                generated_results.append(result)
                if result["baseline"] != result["vf3"]:
                    failures.append(
                        f"generated seed={seed} baseline/vf3 mismatch: baseline={result['baseline']} vf3={result['vf3']}"
                    )
                if result["chatgpt"] != result["vf3"]:
                    failures.append(
                        f"generated seed={seed} chatgpt/vf3 mismatch: chatgpt={result['chatgpt']} vf3={result['vf3']}"
                    )
                if result["gemini"] != result["vf3"]:
                    failures.append(
                        f"generated seed={seed} gemini/vf3 mismatch: gemini={result['gemini']} vf3={result['vf3']}"
                    )

    if failures:
        raise RuntimeError("Glasgow parity check failed:\n" + "\n".join(failures))

    print("Glasgow parity check passed.")
    print(
        f"Small case counts: baseline={baseline_count}, chatgpt={chatgpt_count}, gemini={gemini_count}"
    )
    print(f"SHA256 baseline binary: {baseline_bin_sha}")
    print(f"SHA256 chatgpt source: {chat_src_sha}")
    print(f"SHA256 gemini source:  {gem_src_sha}")
    print(f"SHA256 chatgpt binary: {chat_bin_sha}")
    print(f"SHA256 gemini binary:  {gem_bin_sha}")
    if not args.skip_generated:
        for item in generated_results:
            print(
                "Generated seed={seed}: baseline={baseline} vf3={vf3} chatgpt={chatgpt} gemini={gemini}".format(
                    **item
                )
            )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"[check-glasgow-parity] {exc}", file=sys.stderr)
        raise SystemExit(1)
