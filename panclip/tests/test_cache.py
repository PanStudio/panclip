from panclip.core.cache import SearchCache


async def test_write_invalidates_cached_search():
    cache = SearchCache()
    key, value = await cache.lookup("q", 5)
    assert value is None
    await cache.store(key, {"results": [1]})
    assert (await cache.lookup("q", 5))[1] == {"results": [1]}
    await cache.invalidate()
    assert (await cache.lookup("q", 5))[1] is None


async def test_result_computed_before_a_write_is_not_served_after_it():
    cache = SearchCache()
    stale_key, _ = await cache.lookup("q")
    await cache.invalidate()
    await cache.store(stale_key, {"results": ["stale"]})
    assert (await cache.lookup("q"))[1] is None
