"""Lifecycle management and non-sensitive health reporting for a single worker."""
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from aiohttp import web

logger = logging.getLogger(__name__)


@dataclass
class WorkerState:
    status: str = "starting"
    restarts: int = 0


class TaskSupervisor:
    def __init__(self, base_delay: float = 1.0, max_delay: float = 60.0):
        if base_delay <= 0 or max_delay < base_delay:
            raise ValueError("Invalid restart delays")
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.tasks = {}
        self.states = {}
        self.stopping = False

    def start(self, name: str, factory: Callable[[], Awaitable[None]]):
        if self.stopping:
            raise RuntimeError("Supervisor is stopping")
        if name in self.tasks:
            raise ValueError(f"Worker already registered: {name}")
        state = self.states[name] = WorkerState()
        self.tasks[name] = asyncio.create_task(self._run(name, factory, state), name=name)
        return self.tasks[name]

    async def _run(self, name, factory, state):
        delay = self.base_delay
        try:
            while not self.stopping:
                started = time.monotonic()
                state.status = "running"
                try:
                    await factory()
                    if self.stopping:
                        break
                    logger.error("Background worker %s exited unexpectedly", name)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Background worker %s failed", name)
                if self.stopping:
                    break
                if time.monotonic() - started >= 60:
                    delay = self.base_delay
                state.status = "restarting"
                state.restarts += 1
                await asyncio.sleep(delay)
                delay = min(self.max_delay, delay * 2)
        finally:
            state.status = "stopped"

    def snapshot(self):
        return {name: {"status": state.status, "restarts": state.restarts}
                for name, state in self.states.items()}

    async def stop(self, timeout: float = 15.0):
        self.stopping = True
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=timeout)
            if pending:
                logger.error("%s background workers exceeded shutdown timeout", len(pending))
                for task in pending:
                    task.cancel()


class RuntimeStatus:
    def __init__(self, supervisor: TaskSupervisor):
        self.supervisor = supervisor
        self.started = time.monotonic()
        self.ready = False

    def payload(self):
        workers = self.supervisor.snapshot()
        healthy = self.ready and not self.supervisor.stopping and all(
            worker["status"] == "running" for worker in workers.values()
        )
        return {
            "status": "ok" if healthy else "not_ready",
            "uptime_seconds": int(time.monotonic() - self.started),
            "workers": workers,
        }


def create_health_app(status: RuntimeStatus):
    app = web.Application()

    async def liveness(request):
        return web.json_response({"status": "alive"})

    async def readiness(request):
        payload = status.payload()
        return web.json_response(payload, status=200 if payload["status"] == "ok" else 503)

    app.router.add_get("/", liveness)
    app.router.add_get("/health", readiness)
    app.router.add_get("/ready", readiness)
    return app
