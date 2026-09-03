from app.workers.queue import RedisQueue

__all__ = ["RedisQueue", "Worker"]


def __getattr__(name):
    if name == "Worker":
        from app.workers.tasks import Worker
        return Worker
    raise AttributeError(f"module 'app.workers' has no attribute {name!r}")
