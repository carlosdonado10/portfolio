from control_plane.hub import Hub


async def test_hub_fanout_to_all_tabs():
    hub = Hub()
    async with hub.subscribe("s1") as a, hub.subscribe("s1") as b:
        await hub.publish("s1", {"type": "x"})
        assert await anext(a) == {"type": "x"}
        assert await anext(b) == {"type": "x"}


async def test_hub_connected_until_last_tab_closes():
    hub = Hub()
    assert not hub.connected("s1")
    async with hub.subscribe("s1"):
        async with hub.subscribe("s1"):
            assert hub.connected("s1")
        assert hub.connected("s1")
    assert not hub.connected("s1")


async def test_hub_broadcast_and_isolation():
    hub = Hub()
    async with hub.subscribe("s1") as a, hub.subscribe("s2") as b:
        await hub.publish("s1", {"type": "only1"})
        await hub.broadcast({"type": "all"})
        assert await anext(a) == {"type": "only1"}
        assert await anext(a) == {"type": "all"}
        assert await anext(b) == {"type": "all"}


async def test_hub_publish_without_subscribers_is_noop():
    await Hub().publish("ghost", {"type": "x"})
