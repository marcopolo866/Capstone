"""Regression tests for cross-platform entrypoint wrappers."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(module_name: str, relative_path: str):
    module_path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class PlatformEntrypointTests(unittest.TestCase):
    def test_build_local_prefers_windows_powershell_then_pwsh(self):
        module = load_module("build_local_test_module", "scripts/build-local.py")
        env = {"PATH": "dummy"}

        def fake_which(name: str, path: str | None = None):
            if name == "powershell":
                return r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
            if name == "pwsh":
                return r"C:\Program Files\PowerShell\7\pwsh.exe"
            return None

        with mock.patch.object(module.os, "name", "nt"):
            with mock.patch.object(module.shutil, "which", side_effect=fake_which):
                resolved = module.resolve_powershell_executable(env)

        self.assertEqual(resolved, r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")

    def test_build_local_uses_pwsh_fallback_when_powershell_missing(self):
        module = load_module("build_local_test_module_fallback", "scripts/build-local.py")
        env = {"PATH": "dummy"}

        def fake_which(name: str, path: str | None = None):
            if name == "pwsh":
                return r"C:\Program Files\PowerShell\7\pwsh.exe"
            return None

        with mock.patch.object(module.os, "name", "nt"):
            with mock.patch.object(module.shutil, "which", side_effect=fake_which):
                resolved = module.resolve_powershell_executable(env)

        self.assertEqual(resolved, r"C:\Program Files\PowerShell\7\pwsh.exe")

    def test_build_runner_uses_pwsh_on_non_windows_when_available(self):
        module = load_module("build_runner_test_module", "desktop_runner/build_runner.py")
        env = {"PATH": "dummy"}

        def fake_which(name: str, path: str | None = None):
            if name == "pwsh":
                return "/usr/local/bin/pwsh"
            return None

        with mock.patch.object(module.os, "name", "posix"):
            with mock.patch.object(module.shutil, "which", side_effect=fake_which):
                resolved = module.resolve_powershell_executable(env)

        self.assertEqual(resolved, "/usr/local/bin/pwsh")

    def test_build_local_core_parse_args_accepts_suppress_diagnostics_flag(self):
        module = load_module("build_local_core_test_module", "scripts/build-local-core.py")
        with mock.patch.object(sys, "argv", ["build-local-core.py", "--suppress-diagnostics"]):
            args = module.parse_args()
        self.assertTrue(args.suppress_diagnostics)

    def test_build_local_core_msys_probe_adds_runtime_paths_on_windows(self):
        module = load_module("build_local_core_probe_module", "scripts/build-local-core.py")
        captured = {}
        native_path = type(REPO_ROOT)
        fake_msys_root = native_path("/opt/msys64")
        fake_mingw_bin = fake_msys_root / "mingw64" / "bin"
        fake_usr_bin = fake_msys_root / "usr" / "bin"
        expected_mingw_bin = fake_mingw_bin.resolve()
        expected_usr_bin = expected_mingw_bin.parent.parent / "usr" / "bin"

        class DummyCompleted:
            returncode = 0

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = dict(kwargs)
            captured["path"] = module.os.environ.get("PATH", "")
            output_path = Path(cmd[-1])
            output_path.write_text("ok", encoding="utf-8")
            return DummyCompleted()

        fake_gpp = fake_mingw_bin / "g++.exe"
        with mock.patch.object(module, "Path", native_path):
            with mock.patch.object(module.os, "name", "nt"):
                with mock.patch.object(module.Path, "is_dir", autospec=True, side_effect=lambda path: path == expected_usr_bin):
                    with mock.patch.object(module.subprocess, "run", side_effect=fake_run):
                        ok = module._compiler_can_compile_cpp(fake_gpp, env={"PATH": str(native_path("/opt/mingw64/bin"))})

        self.assertTrue(ok)
        self.assertNotIn("env", captured["kwargs"])
        probe_path = captured["path"]
        self.assertIn(str(expected_mingw_bin), probe_path)
        self.assertIn(str(expected_usr_bin), probe_path)

    def test_build_local_core_run_subprocess_avoids_env_kwarg_on_windows(self):
        module = load_module("build_local_core_run_module", "scripts/build-local-core.py")
        captured = {}

        class DummyCompleted:
            returncode = 0

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = dict(kwargs)
            return DummyCompleted()

        with mock.patch.object(module.os, "name", "nt"):
            with mock.patch.object(module.subprocess, "run", side_effect=fake_run):
                result = module.run_subprocess(["g++", "--version"], env={"PATH": r"C:\msys64\mingw64\bin"})

        self.assertEqual(result.returncode, 0)
        self.assertEqual(captured["cmd"], ["g++", "--version"])
        self.assertNotIn("env", captured["kwargs"])


if __name__ == "__main__":
    unittest.main()
