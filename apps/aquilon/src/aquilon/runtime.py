"""Local draft runtime composition; no platform API/model imports."""
from datetime import datetime

from .adapter import ChirpStackAdapter
from .spool import SQLiteSpool
from .wire import Rejected


class AquilonRuntime:
    def __init__(self, adapter: ChirpStackAdapter, spool: SQLiteSpool):
        self.adapter, self.spool = adapter, spool

    def ingest(self, body: bytes, *, event: str, received_at: datetime,
               transport="fixture-replay", integration_id="synthetic-local"):
        try:
            accepted = self.adapter.parse(body, event=event, received_at=received_at,
                                          transport=transport, integration_id=integration_id)
        except Rejected:
            self.spool.count("parser_rejected")
            raise
        outcome = self.spool.enqueue(accepted, now=received_at.timestamp())
        return {"status": outcome, "identity": accepted.identity}

    def health(self):
        return {"contract_status": "draft-unapproved", "platform_ingest": "not-integrated",
                "registry": "local-reference-only", "spool": self.spool.health()}
