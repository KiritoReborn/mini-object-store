import asyncio
import logging

import httpx

from . import config

log = logging.getLogger("worker")


async def register(client):
    while True:
        try:
            r = await client.post(
                f"{config.CONTROLLER_URL}/internal/workers/register",
                json={"worker_id": config.WORKER_ID, "base_url": config.BASE_URL},
            )
            if r.is_success:
                log.info("REGISTERED worker=%s", config.WORKER_ID)
                return
            log.warning("register worker=%s got %s", config.WORKER_ID, r.status_code)
        except httpx.HTTPError as e:
            log.warning("register worker=%s failed: %r", config.WORKER_ID, e)
        except Exception:
            log.exception("register worker=%s unexpected failure", config.WORKER_ID)
        await asyncio.sleep(2)


async def run_heartbeat():
    async with httpx.AsyncClient(timeout=5) as client:
        await register(client)
        while True:
            await asyncio.sleep(config.HEARTBEAT_INTERVAL)
            try:
                r = await client.post(
                    f"{config.CONTROLLER_URL}/internal/workers/heartbeat",
                    json={"worker_id": config.WORKER_ID},
                )
                if r.status_code == 404:  # controller doesn't know us (restarted)
                    await register(client)
                elif not r.is_success:
                    log.warning("heartbeat worker=%s got %s", config.WORKER_ID, r.status_code)
            except httpx.HTTPError as e:
                log.warning("heartbeat worker=%s failed: %r", config.WORKER_ID, e)
            except Exception:
                log.exception("heartbeat worker=%s unexpected failure", config.WORKER_ID)
