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


class RecordingQueue:
    """Fake queue recording enqueue/push_dead calls (with a real Worker)."""

    def __init__(self, max_attempts=3, dequeue_sequence=None):
        self.max_attempts = max_attempts
        self._dequeue_sequence = list(dequeue_sequence or [])
        self.enqueued = []
        self.dead = []

    async def dequeue(self, timeout=2):
        if self._dequeue_sequence:
            return self._dequeue_sequence.pop(0)
        return None

    async def enqueue(self, raw_msg):
        self.enqueued.append(raw_msg)

    async def push_dead(self, raw_msg):
        self.dead.append(raw_msg)


def _msg(id="m1", attempts=0):
    return RawMessage(
        id=id,
        source="telegram",
        source_message_id="100",
        source_chat_id="@promo_deals",
        text="🔥 TV 50 4K\nhttps://www.amazon.com.br/dp/B08N5WRWNW",
        attempts=attempts,
    )


@pytest.mark.asyncio
async def test_failure_re_enqueues_with_incremented_attempts():
    worker = Worker()
    msg = _msg(id="m1", attempts=0)
    queue = RecordingQueue(max_attempts=3)
    worker.queue = queue

    await worker._handle_failure(msg)

    assert len(queue.enqueued) == 1
    assert queue.enqueued[0].id == "m1"
    assert queue.enqueued[0].attempts == 1
    assert queue.dead == []


@pytest.mark.asyncio
async def test_failure_re_enqueues_below_max_attempts():
    worker = Worker()
    msg = _msg(id="m1", attempts=1)
    queue = RecordingQueue(max_attempts=3)
    worker.queue = queue

    await worker._handle_failure(msg)

    assert len(queue.enqueued) == 1
    assert queue.enqueued[0].attempts == 2
    assert queue.dead == []


@pytest.mark.asyncio
async def test_failure_exceeding_max_attempts_goes_to_dead_letter():
    worker = Worker()
    msg = _msg(id="m1", attempts=2)  # 2 -> 3 = max, so dead-letter
    queue = RecordingQueue(max_attempts=3)
    worker.queue = queue

    await worker._handle_failure(msg)

    assert queue.enqueued == []
    assert len(queue.dead) == 1
    assert queue.dead[0].id == "m1"
    assert queue.dead[0].attempts == 3


@pytest.mark.asyncio
async def test_worker_loop_retries_failure_then_succeeds():
    """A failure is re-enqueued; on the retry the processor succeeds and stops."""
    calls = []

    class FakePromo:
        status = "published"

    class FlakyProcessor:
        async def process(self, raw_msg, db_session=None):
            calls.append((raw_msg.id, raw_msg.attempts))
            if len(calls) == 1:
                return None  # transient failure
            return FakePromo()  # success

    # Sequence: first attempt (fails) -> worker re-enqueues -> second attempt (succeeds)
    queue = RecordingQueue(
        max_attempts=3,
        dequeue_sequence=[_msg(id="m1", attempts=0), _msg(id="m1", attempts=1), None],
    )
    worker = Worker()
    worker.queue = queue
    worker.processor = FlakyProcessor()

    async def bounded_start():
        while True:
            raw_msg = await worker.queue.dequeue(timeout=0)
            if not raw_msg:
                break
            result = await worker.processor.process(raw_msg, db_session=None)
            if result is None or getattr(result, "status", None) == "failed":
                await worker._handle_failure(raw_msg)

    with patch("app.workers.tasks.init_db", new=AsyncMock()):
        await bounded_start()

    # First attempt re-enqueued, second succeeded (no dead-letter)
    assert len(queue.enqueued) == 1
    assert queue.enqueued[0].attempts == 1
    assert queue.dead == []
    assert calls == [("m1", 0), ("m1", 1)]


@pytest.mark.asyncio
async def test_worker_loop_sends_to_dead_letter_after_max_attempts():
    queue = RecordingQueue(
        max_attempts=2,
        dequeue_sequence=[_msg(id="m1", attempts=0), _msg(id="m1", attempts=1), None],
    )

    class AlwaysFail:
        async def process(self, raw_msg, db_session=None):
            return None  # always fails

    worker = Worker()
    worker.queue = queue
    worker.processor = AlwaysFail()

    async def bounded_start():
        while True:
            raw_msg = await worker.queue.dequeue(timeout=0)
            if not raw_msg:
                break
            result = await worker.processor.process(raw_msg, db_session=None)
            if result is None or getattr(result, "status", None) == "failed":
                await worker._handle_failure(raw_msg)

    with patch("app.workers.tasks.init_db", new=AsyncMock()):
        await bounded_start()

    # attempts 0->1 re-enqueued, then 1->2 = max -> dead-letter, no further re-enqueue
    assert len(queue.enqueued) == 1
    assert queue.enqueued[0].attempts == 1
    assert len(queue.dead) == 1
    assert queue.dead[0].attempts == 2
