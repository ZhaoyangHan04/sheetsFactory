"""Network-isolated LibreOffice calculation through an immutable Docker image."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import threading
import uuid


class WorkbookEngineError(RuntimeError):
    pass


_BUILD_LOCK = threading.Lock()


class LibreOfficeEngine:
    def __init__(self, project_root: Path, image: str = "sheetsfactory-lo:24.2",
                 timeout_seconds: int = 120):
        self.project_root = Path(project_root).resolve()
        self.image = image
        self.timeout_seconds = timeout_seconds
        self.image_id: str | None = None

    def ensure_image(self) -> str:
        if self.image_id:
            return self.image_id
        if shutil.which("docker") is None:
            raise WorkbookEngineError("Docker is required for LibreOffice calculation")
        with _BUILD_LOCK:
            result = subprocess.run(["docker", "image", "inspect", self.image,
                                     "--format", "{{.Id}}"], capture_output=True, text=True)
            if result.returncode:
                context = Path(__file__).resolve().parent
                result = subprocess.run(["docker", "build", "--network", "host",
                                         "-t", self.image, str(context)],
                                        capture_output=True, text=True, timeout=900)
                if result.returncode:
                    raise WorkbookEngineError("LibreOffice image build failed: " + result.stderr[-2000:])
                result = subprocess.run(["docker", "image", "inspect", self.image,
                                         "--format", "{{.Id}}"], capture_output=True, text=True, check=True)
            self.image_id = result.stdout.strip()
        return self.image_id

    def metadata(self) -> dict:
        image_id = self.ensure_image()
        result = subprocess.run(["docker", "run", "--rm", "--user", "0", "--workdir", "/tmp", "--network", "none",
                                 "--entrypoint", "/usr/bin/libreoffice", image_id, "--version"],
                                capture_output=True, text=True, timeout=30)
        return {"backend": "libreoffice_uno_docker", "image": self.image,
                "image_id": image_id, "version": result.stdout.strip(),
                "network": "none", "macro_execution": "never", "external_updates": "never"}

    def normalize(self, source: Path, destination: Path) -> Path:
        return self.recalculate(source, destination)

    def recalculate(self, source: Path, destination: Path) -> Path:
        source, destination = Path(source).resolve(), Path(destination).resolve()
        if not source.is_file():
            raise WorkbookEngineError(f"Source workbook not found: {source.name}")
        if source.suffix.lower() not in {".xls", ".xlsx"}:
            raise WorkbookEngineError("Only .xls and .xlsx sources are supported")
        if destination.suffix.lower() != ".xlsx":
            raise WorkbookEngineError("Normalized output must be .xlsx")
        image_id = self.ensure_image()
        name = "sf-lo-" + uuid.uuid4().hex[:20]
        container_input = "/tmp/source" + source.suffix.lower()
        container_output = "/tmp/result.xlsx"
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            self._run(["docker", "create", "--name", name, "--user", "0", "--workdir", "/tmp", "--network", "none",
                       "--cap-drop", "ALL", "--cap-add", "DAC_OVERRIDE",
                       "--security-opt", "no-new-privileges",
                       "--memory", "2g", "--cpus", "2", "--pids-limit", "256",
                       image_id, container_input, container_output], timeout=30)
            self._run(["docker", "cp", str(source), name + ":" + container_input], timeout=30)
            self._run(["docker", "start", "--attach", name], timeout=self.timeout_seconds)
            state = self._run(["docker", "inspect", name, "--format", "{{.State.ExitCode}}"], timeout=15)
            if state.strip() != "0":
                raise WorkbookEngineError("LibreOffice container exited with status " + state.strip())
            self._run(["docker", "cp", name + ":" + container_output, str(temporary)], timeout=30)
            if not temporary.is_file() or temporary.stat().st_size < 100:
                raise WorkbookEngineError("LibreOffice did not create a valid output file")
            temporary.replace(destination)
            return destination
        finally:
            subprocess.run(["docker", "rm", "--force", name], capture_output=True, timeout=20)
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _run(command: list[str], timeout: int) -> str:
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise WorkbookEngineError(f"Workbook engine timed out after {timeout}s") from exc
        if result.returncode:
            raise WorkbookEngineError("Workbook engine command failed: " + result.stderr[-2000:])
        return result.stdout

    def check_stable(self, source: Path, directory: Path) -> dict:
        from .compare import compare_workbooks
        directory = Path(directory)
        first = self.recalculate(source, directory / "pass1.xlsx")
        second = self.recalculate(first, directory / "pass2.xlsx")
        comparison = compare_workbooks(first, first, second)
        return {"stable": comparison["reward"] == 1,
                "comparison": comparison, "first": str(first), "second": str(second)}
