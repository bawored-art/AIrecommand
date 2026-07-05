from common.cache import FileCache


def test_set_and_get_roundtrip(tmp_path):
    cache = FileCache(cache_dir=str(tmp_path), default_ttl_seconds=3600)
    cache.set("key1", {"a": 1})
    assert cache.get("key1") == {"a": 1}


def test_get_returns_none_for_missing_key(tmp_path):
    cache = FileCache(cache_dir=str(tmp_path), default_ttl_seconds=3600)
    assert cache.get("missing") is None


def test_expired_entry_returns_none(tmp_path):
    cache = FileCache(cache_dir=str(tmp_path), default_ttl_seconds=3600)
    cache.set("key1", {"a": 1}, ttl_seconds=-1)
    assert cache.get("key1") is None


def test_get_or_set_only_calls_fetch_fn_once(tmp_path):
    cache = FileCache(cache_dir=str(tmp_path), default_ttl_seconds=3600)
    calls = []

    def fetch():
        calls.append(1)
        return {"value": 42}

    first = cache.get_or_set("key1", fetch)
    second = cache.get_or_set("key1", fetch)

    assert first == second == {"value": 42}
    assert len(calls) == 1
