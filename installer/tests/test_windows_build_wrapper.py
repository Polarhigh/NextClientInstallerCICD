from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


kRoot = Path(__file__).resolve().parents[2]
kScript = kRoot / "tools/installer/build_installer.ps1"
kShells = [path for name in ("powershell.exe", "pwsh.exe") if (path := shutil.which(name))]


@unittest.skipUnless(sys.platform == "win32" and kShells, "Windows PowerShell is required")
class WindowsBuildWrapperTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="installer wrapper & spaces ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.payload = self.root / "payload"
        self.payload.mkdir()
        self.tools = self.root / "tools"

    def Run(self, shell, *arguments):
        return subprocess.run([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "RemoteSigned",
                               "-File", str(kScript), *map(str, arguments)],
                              cwd=self.root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25)

    def test_help_does_not_prepare_tools(self):
        for shell in kShells:
            with self.subTest(shell=shell):
                result = self.Run(shell, "-Help")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("Payload", result.stdout)
                self.assertIn("SmokeTest", result.stdout)
                self.assertFalse(self.tools.exists())

    def test_inno_relative_destination_uses_powershell_location(self):
        initial = self.root / "initial"
        for directory in (self.tools, initial / "tools"):
            directory.mkdir(parents=True)
            (directory / "ISCC.exe").write_bytes(b"cached compiler marker")
        location = str(self.root).replace("'", "''")
        script = str(kRoot / "tools/installer/install_inno.ps1").replace("'", "''")
        command = f"Set-Location -LiteralPath '{location}'; & '{script}' -Destination 'tools'"
        for shell in kShells:
            with self.subTest(shell=shell):
                result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "RemoteSigned",
                                         "-Command", command], cwd=initial, capture_output=True,
                                        text=True, encoding="utf-8", errors="replace", timeout=25)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(Path(result.stdout.strip()), self.tools / "ISCC.exe")

    def test_missing_payload_fails_before_tool_preparation(self):
        for shell in kShells:
            with self.subTest(shell=shell):
                result = self.Run(shell, "-Payload", self.root / "missing", "-ToolsDirectory", self.tools)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Release payload directory does not exist", result.stdout + result.stderr)
                self.assertFalse(self.tools.exists())

    def test_invalid_version_cannot_create_output_or_tools(self):
        for shell in kShells:
            with self.subTest(shell=shell):
                result = self.Run(shell, "-Payload", self.payload, "-Version", "../../outside", "-ToolsDirectory", self.tools)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Invalid installer version", result.stdout + result.stderr)
                self.assertFalse(self.tools.exists())
                self.assertFalse((self.root / "outside").exists())

    def test_missing_explicit_compiler_stops_before_tool_preparation(self):
        for shell in kShells:
            with self.subTest(shell=shell):
                result = self.Run(shell, "-Payload", self.payload, "-Iscc", self.root / "missing ISCC.exe",
                                  "-ToolsDirectory", self.tools)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Inno Setup compiler does not exist", result.stdout + result.stderr)
                self.assertFalse(self.tools.exists())

    def test_python_failure_stops_before_dependency_installation(self):
        python = self.root / "failing python.cmd"
        python.write_text('@echo off\necho Interpreter probe failed 1>&2\nexit /b 7\n', encoding="ascii")
        for shell in kShells:
            with self.subTest(shell=shell):
                result = self.Run(shell, "-Payload", self.payload, "-Version", "1.2.3-test", "-Python", python,
                                  "-ToolsDirectory", self.tools)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("exit code 7", result.stdout + result.stderr)
                self.assertFalse(self.tools.exists())
