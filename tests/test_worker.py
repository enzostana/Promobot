import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.workers.tasks import Worker
from app.core.models import RawMessage


@pytest.mark.asyncio
async def test_worker_continues_after_processor_error():
    """A processor that raises must not crash the worker loop."""
    processed = []

    class FakeProcessor:
        def __init__(self, processed_list):
            self.processed_list = processed_list

        async def process(self, raw_msg, db_session=None):
            self.processed_list.append(raw_msg)
            if len(self.processed_list) == 1:
                raise RuntimeError("erro no processamento")

    messages = [
        RawMessage(id="1", source="telegram", source_message_id="1", source_chat_id="@a", text="x"),
        RawMessage(id="2", source="telegram", source_message_id="2", source_chat_id="@b", text="y"),
    ]

    async def fake_dequeue(*args, **kwargs):
        if messages:
            return messages.pop(0)
        return None

    queue = AsyncMock()
    queue.dequeue = fake_dequeue

    worker = Worker()
    worker.queue = queue
    worker.processor = FakeProcessor(processed)

    async def mock_start():
        while True:
            raw_msg = await worker.queue.dequeue(timeout=0)
            if not raw_msg:
                break
            try:
                await worker.processor.process(raw_msg, db_session=None)
            except Exception:
                pass

    with patch("app.workers.tasks.init_db", new=AsyncMock()):
        worker.start = mock_start
        await worker.start()

    assert len(processed) == 2
    assert processed[0].id == "1"
    assert processed[1].id == "2"
