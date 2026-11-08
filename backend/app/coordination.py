"""Serialize state accounting in the single-process local SQLite deployment."""
from functools import wraps
from threading import RLock

state_lock = RLock()


def serialized(function):
    @wraps(function)
    def call(*args, **kwargs):
        with state_lock:
            return function(*args, **kwargs)
    return call
