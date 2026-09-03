import pytest
from fakeredis.aioredis import FakeRedis

from app.config.settings import Settings
from app.core.models import RawMessage
from app.workers.queue import RedisQueue


@pytest.fixture
def settings():
    return Settings(
        APP_ENV="test",
        DEBUG=True,
        REDIS_QUEUE_NAME="promobot:test",
        WORKER_MAX_ATTEMPTS=3,
    )


@pytest.fixture
def fake_client():
    return FakeRedis(decode_responses=True)


@pytest.fixture
def queue(settings, fake_client):
    return RedisQueue(settings=settings, client=fake_client)


def _message(id="m1"):
    return RawMessage(
        id=id,
        source="telegram",
        source_message_id="100",
        source_chat_id="@promo_deals",
        text="🔥 TV 50 4K\nhttps://www.amazon.com.br/dp/B08N5WRWNW",
    )


@pytest.mark.asyncio
async def test_enqueue_dequeue_roundtrip(queue):
    await queue.enqueue(_message("roundtrip"))

    assert await queue.length() == 1
    msg = await queue.dequeue(timeout=0.1)
    assert msg is not None
    assert msg.id == "roundtrip"
    assert msg.source_chat_id == "@promo_deals"
    assert msg.text == "🔥 TV 50 4K\nhttps://www.amazon.com.br/dp/B08N5WRWNW"


@pytest.mark.asyncio
async def test_dequeue_empty_returns_none(queue):
    assert await queue.dequeue(timeout=0.1) is None


@pytest.mark.asyncio
async def test_dequeue_is_fifo(queue):
    await queue.enqueue(_message("first"))
    await queue.enqueue(_message("second"))

    first = await queue.dequeue(timeout=0.1)
    second = await queue.dequeue(timeout=0.1)
    assert first.id == "first"
    assert second.id == "second"


@pytest.mark.asyncio
async def test_attempts_field_roundtrips(queue):
    msg = _message("tries")
    msg.attempts = 2
    await queue.enqueue(msg)

    got = await queue.dequeue(timeout=0.1)
    assert got.attempts == 2


@pytest.mark.asyncio
async def test_push_dead_separate_from_main_queue(queue, fake_client):
    exhausted = _message("dead")
    exhausted.attempts = 3

    await queue.push_dead(exhausted)

    # Dead message is NOT readable from the main queue
    assert await queue.dequeue(timeout=0.1) is None
    assert await queue.length() == 0

    # It lives in the dead-letter queue
    dead_len = await fake_client.llen(queue.dead_queue_name)
    assert dead_len == 1
    dead_item = await fake_client.blpop([queue.dead_queue_name], timeout=0.1)
    assert dead_item is not None
    assert "dead" in dead_item[1]


@pytest.mark.asyncio
async def test_queue_respects_fifo_ordering_across_messages(queue):
    for i in range(3):
        await queue.enqueue(_message(f"order-{i}"))

    ids = []
    for _ in range(3):
        msg = await queue.dequeue(timeout=0.1)
        ids.append(msg.id)

    assert ids == ["order-0", "order-1", "order-2"]