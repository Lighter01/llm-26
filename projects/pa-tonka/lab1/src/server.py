from pathlib import Path
from subprocess import STDOUT, Popen, TimeoutExpired
from time import perf_counter, sleep

from httpx import Client, RequestError


class LlamaServer:
    def __init__(
        self,
        model_path: Path,
        log_path: Path,
        command: tuple[str, ...] = ('llama', 'serve'),
        host: str = "127.0.0.1",
        port: int = 9931,
        context_size: int = 4096,
        timeout_s: int = 120,
        interval_s: float = 0.5,
    ):
        self.model_path = model_path
        self.command = command
        self.host = host
        self.port = port
        self.context_size = context_size
        self.log_path = log_path

        self.timeout_s = timeout_s
        self.interval_s = interval_s

        self._server_process: Popen | None = None
        self._log_file = None

    def _build_command(self) -> list[str]:
        return [
            *self.command,
            "-m", str(self.model_path),
            "--host", str(self.host),
            "--port", str(self.port), 
            "--ctx-size", str(self.context_size),
            "--parallel", "1",
            "--no-cache-prompt", 
            "--reasoning", "off",
        ]

    def start(self) -> None:
        if self._server_process is not None:
            raise RuntimeError("Server is already running")
        
        self.log_path.parent.mkdir(exist_ok=True, parents=True)
        self._log_file = self.log_path.open(mode="wb")
        
        try:
            self._server_process = Popen(
                self._build_command(),
                stdout=self._log_file,
                stderr=STDOUT,
            )
        except BaseException:
            # Popen failed, so don't leak the opened file.
            self._log_file.close()
            self._log_file = None
            raise

    def stop(self) -> None:
        try:
            if self._server_process is not None and self._server_process.poll() is None:
                self._server_process.terminate()

                try:
                    self._server_process.wait(timeout=5)
                except TimeoutExpired:
                    self._server_process.kill()
                    self._server_process.wait()
        finally:
            self._server_process = None

            if self._log_file is not None:
                self._log_file.close()
                self._log_file = None

    def _wait_until_ready(self) -> None:
        process = self._server_process

        if process is None:
            raise RuntimeError("Server has not been started")

        deadline = perf_counter() + self.timeout_s

        with Client(
            base_url=f"http://{self.host}:{self.port}",
            timeout=1.0,
            # trust_env=False,
        ) as client:
            while perf_counter() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(
                        f"llama-server exited with code {process.returncode}"
                    )

                try:
                    response = client.get("/health")

                    if response.status_code == 200:
                        return

                    if response.status_code != 503:
                        response.raise_for_status()

                except RequestError:
                    # The server may not be listening yet.
                    pass

                sleep(self.interval_s)

        raise TimeoutError(
            f"llama-server did not become ready within "
            f"{self.timeout_s} seconds"
        )

    def __enter__(self):
        try:
            self.start()
            self._wait_until_ready()
            return self
        except BaseException:
            self.stop()
            raise

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop()
        return False


if __name__ == "__main__":
    ...