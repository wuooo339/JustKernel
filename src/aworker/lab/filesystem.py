"""Pinned Deep Agents filesystem with explicit UTF-8 ripgrep pipes on Windows."""

import shutil
import subprocess
import threading

from deepagents.backends import FilesystemBackend


# ---- UTF8FilesystemBackend --------------------------------------------------
class UTF8FilesystemBackend(FilesystemBackend):
    # ---- bounded ripgrep stream ---------------------------------------------
    def _ripgrep_search(self, pattern, base_full, include_glob, max_count=None):
        binary = shutil.which("rg")
        if binary is None:
            return None, False
        command = [binary, "--json", "-F"]
        if include_glob:
            command.extend(["--glob", include_glob])
        cwd = base_full if base_full.is_dir() else None
        command.extend(["--", pattern, "." if cwd else str(base_full)])
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            return None, False
        expired = threading.Event()

        def stop():
            expired.set()
            process.terminate()

        timer = threading.Timer(10, stop)
        timer.start()
        matches, count, truncated = {}, 0, False
        try:
            for line in process.stdout:
                parsed = self._parse_rg_match(line, base_full, base_full.resolve())
                if parsed is None:
                    continue
                if max_count is not None and count >= max_count:
                    truncated = True
                    process.terminate()
                    break
                path, number, text = parsed
                matches.setdefault(path, []).append((number, text))
                count += 1
        finally:
            timer.cancel()
            self._reap_ripgrep(process)
        if expired.is_set():
            return (matches, True) if matches else (None, False)
        if not truncated and process.returncode not in {0, 1}:
            return None, False
        return matches, truncated
