"""Local API event-loop pulse plus an independent digital watchdog sampler."""
import asyncio
import logging
import threading

LOGGER = logging.getLogger("poseidon_api")


async def event_loop_pulse(hub):
    while True:
        hub._watchdogs.heartbeat("host")
        await asyncio.sleep(0.25)


def sample_loop(hub, stop: threading.Event):
    while not stop.wait(0.5):
        try:
            hub._watchdog_tick()
        except Exception as exc:
            # Cannot safely record state: stop supervision, refuse the API control
            # boundary. Never rewrite corrupt DB/evidence to claim a stored fault.
            LOGGER.error("digital watchdog storage unavailable: %s", type(exc).__name__)
            hub._control_unavailable = True
            return
