import os
import json
import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import List, Dict, Any, Optional
import pandas as pd
from filelock import FileLock

from logai.pattern import Pattern

#MAX_WORKERS = max(1, (os.cpu_count() or 2) - 1)
MAX_WORKERS = 2  # limit to 4 workers for now due to memory constraints

# ---------- Helpers ----------
def status_file(project_dir: Path) -> Path:
    return Path(project_dir / "status.json")

def read_status(project_dir: Path) -> Dict[str, Any]:
    sf = status_file(project_dir)
    if not sf.exists():
        return {}
    try:
        return json.loads(sf.read_text(encoding="utf-8"))
    except Exception:
        return {}

def write_status_atomically(project_dir: Path, status_obj: Dict[str, Any]) -> None:
    sf = status_file(project_dir)
    tmp = sf.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(status_obj, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(sf))

def update_file_status(project_dir: Path, filename: str, state: str, meta: Optional[Dict[str,Any]] = None):
    """Update status.json for a single file with atomic write."""
    status = read_status(project_dir)
    status.setdefault(filename, {})
    status[filename].update({
        "state": state,
        "timestamp": time.time()
    })
    if meta:
        status[filename].update(meta)
    write_status_atomically(project_dir, status)

'''
class FileLockTimeout(Exception):
    pass

class FileLock:
    """
    Simple lock implemented by creating a lock directory.
    Writes metadata (pid,timestamp) into the dir so other processes can
    detect stale locks. Uses retries and supports stale timeout.
    Usage:
        with FileLock(project_id, filename, lock_root=..., stale_after=600, wait=0.1, attempts=300):
            # do critical section
    """
    def __init__(self, project_dir, filename, stale_after: int = 600,
                 wait: float = 0.1, attempts: int = 50):
        self.lock_root = project_dir
        self.filename = str(filename)
        self.stale_after = int(stale_after)
        self.wait = float(wait)
        self.attempts = int(attempts)
        self.lockdir = self.lock_root / f"{self.filename}.lock"
        self.meta_file = self.lockdir / "meta.json"
        self.acquired = False

    def _write_meta(self):
        meta = {
            "pid": os.getpid(),
            "ts": time.time()
        }
        try:
            self.meta_file.write_text(f"{meta['pid']},{int(meta['ts'])}", encoding="utf-8")
        except Exception:
            # best-effort
            pass

    def _is_stale(self):
        try:
            txt = self.meta_file.read_text(encoding="utf-8")
            pid_str, ts_str = txt.split(",", 1)
            ts = int(ts_str)
            age = time.time() - ts
            return age > self.stale_after
        except Exception:
            # if can't read meta, treat lock as stale if folder older than stale_after
            try:
                mtime = self.lockdir.stat().st_mtime
                return (time.time() - mtime) > self.stale_after
            except Exception:
                return False

    def acquire(self, block=True):
        #print(f"Acquiring lock for {self.filename} at {self.lockdir}")
        attempts = 0
        while True:
            try:
                # atomic mkdir
                os.mkdir(self.lockdir)
                # write metadata
                self._write_meta()
                self.acquired = True
                #print(f"Acquired lock for {self.filename}")
                return True
            except FileExistsError:
                # check stale
                if self._is_stale():
                    # try to remove stale lock dir (best-effort)
                    try:
                        # remove possible meta then dir
                        for child in self.lockdir.iterdir():
                            try:
                                child.unlink()
                            except Exception:
                                pass
                        self.lockdir.rmdir()
                    except Exception:
                        # couldn't remove stale lock; fall through to wait/retry
                        pass
                    # after cleanup attempt, loop to try again immediately
                    attempts += 1
                else:
                    attempts += 1

                if not block or attempts >= self.attempts:
                    return False
                time.sleep(self.wait)
            except OSError as e:
                # treat other OS errors as fatal after some attempts
                attempts += 1
                if attempts >= self.attempts:
                    return False
                time.sleep(self.wait)

    def release(self):
        if not self.acquired:
            return
        # remove meta if present then remove dir
        try:
            if self.meta_file.exists():
                try:
                    self.meta_file.unlink()
                except Exception:
                    pass
            if self.lockdir.exists():
                try:
                    self.lockdir.rmdir()
                except OSError:
                    # if directory not empty, try to remove children then dir
                    for child in self.lockdir.iterdir():
                        try:
                            child.unlink()
                        except Exception:
                            pass
                    try:
                        self.lockdir.rmdir()
                    except Exception:
                        pass
        finally:
            self.acquired = False

    def __enter__(self):
        ok = self.acquire(block=True)
        if not ok:
            raise FileLockTimeout(f"Could not acquire lock {self.lockdir}")
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self.release()
        except Exception:
            pass
'''
# ---------- Worker function (must be importable at top-level for ProcessPool) ----------
def _parse_file_worker(project_dir: Path, filename: str, original_filename: str, file_path) -> Dict[str,Any]:
    """
    Worker executed in subprocess. Parses file with Drain3 and writes parquet result atomically.
    Returns status dict (state, message).
    """
    try:
        #with FileLock(project_dir, filename, stale_after=600, wait=0.1, attempts=200):
        
        lock_file= file_path + ".lock"
        #print("lock file",lock_file)
        lock = FileLock(lock_file=lock_file)
        with lock:
            #print(f"Parsing {filename} in {project_dir}")
            parser = Pattern(project_dir=project_dir)
            parser.parse_logs(file_path)
            #print(f"Parsed {filename}, result at {result_df_path}")

            return {"state": "done", "message": "Parsed and saved"}
    except Exception as e:
        #print("Exception occured")
        return {"state": "error", "message": str(e)}
    finally:
        if lock.is_locked:
            #print("release lock")
            lock.release()
        if os.path.exists(lock_file):
            #print("Error Lock file still Exists, need manual removal")
            os.remove(lock_file)

class PatternScheduler:
    non_text_extensions = ['.xls', '.xlsx', '.tgz', '.zip']
    ignore_filename_list = ['telemetry2', 'snapshot']
    """Holds a process pool and schedules parse jobs per project."""
    def __init__(self, max_workers: int = MAX_WORKERS):
        self.pool = ProcessPoolExecutor(max_workers=max_workers)
        # bookkeeping future -> (project_dir, filename)
        self._futures = {}

    def schedule_files(self, project_dir, files) -> Dict[str,str]:
        """
        Schedule files for parsing. Returns dict filename -> status message (queued/skipped/already).
        """
        if not os.path.exists(project_dir) or not files:
            return {}
        # ensure lock dir exists
        #(project_dir / "locks").mkdir(parents=True, exist_ok=True)
        results = {}

        for filename, file_path, original_name, _, _ in files:
            if not os.path.exists(file_path):
                continue

            if not os.path.getsize(file_path):
                continue

            if any(filename.endswith(ext) for ext in self.non_text_extensions):
                continue

            if any(ign.lower() in original_name.lower() for ign in self.ignore_filename_list):
                continue

            result_path = Path(file_path + ".parquet")
            #print(f"Checking if result exists at {result_path}")
            if result_path.exists():
                results[original_name] = "parsed"
                continue

            # if already processing according to status.json, skip
            status = read_status(project_dir).get(original_name, {})
            if status.get("state") == "queued":
                continue

            # mark queued and release the lock (worker will re-acquire). We keep a tiny window:
            update_file_status(project_dir, original_name, "queued", {"queued_at": time.time()})

            # schedule worker in pool
            #print(f"Scheduling parsing for {filename}")
            future = self.pool.submit(_parse_file_worker, project_dir, filename, original_name, file_path)
            self._futures[future] = (project_dir, filename)
            #print(f"Scheduled parsing for {filename}")
            results[filename] = "scheduled"
        return results

    def poll_futures(self, project_dir, filename):
        """Check completed futures and update status.json accordingly."""
        done = {}
        for fut in list(self._futures.keys()):
            if fut.done():
                project_dir, filename = self._futures.pop(fut)
                try:
                    res = fut.result()
                except Exception as e:
                    res = {"state": "error", "message": str(e)}
                state = res.get("state", "error")
                update_file_status(project_dir, filename, state, {"message": res.get("message")})
                done[(project_dir, filename)] = res
        return done

    def shutdown(self):
        self.pool.shutdown(wait=True)
