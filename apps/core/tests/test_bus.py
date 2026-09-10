"""In-process async event bus with wildcard subscriptions."""
import asyncio

import pytest

from nero_core.bus import EventBus
from nero_core.protocol import Event


async def test_subscriber_receives_matching_event():
    bus = EventBus()
    got = []
    bus.subscribe("device.online", lambda e: got.append(e))
    await bus.publish(Event(type="device.online", payload={"device_id": "d"}))
    assert [e.type for e in got] == ["device.online"]


async def test_prefix_wildcard_matches_namespace():
    bus = EventBus()
    got = []
    bus.subscribe("device.*", lambda e: got.append(e.type))
    await bus.publish(Event(type="device.online"))
    await bus.publish(Event(type="device.action.started"))
    await bus.publish(Event(type="hermes.tool.started"))
    assert got == ["device.online", "device.action.started"]


async def test_star_matches_everything():
    bus = EventBus()
    got = []
    bus.subscribe("*", lambda e: got.append(e.type))
    await bus.publish(Event(type="a.b"))
    await bus.publish(Event(type="c.d"))
    assert got == ["a.b", "c.d"]


async def test_async_handlers_are_awaited():
    bus = EventBus()
    got = []

    async def h(e):
        await asyncio.sleep(0)
        got.append(e.type)

    bus.subscribe("x.y", h)
    await bus.publish(Event(type="x.y"))
    assert got == ["x.y"]


async def test_failing_handler_does_not_break_others(caplog):
    bus = EventBus()
    got = []

    def bad(e):
        raise RuntimeError("boom")

    bus.subscribe("x.y", bad)
    bus.subscribe("x.y", lambda e: got.append(1))
    await bus.publish(Event(type="x.y"))
    assert got == [1]
    assert "boom" in caplog.text


async def test_unsubscribe_stops_delivery():
    bus = EventBus()
    got = []
    unsub = bus.subscribe("x.y", lambda e: got.append(1))
    await bus.publish(Event(type="x.y"))
    unsub()
    await bus.publish(Event(type="x.y"))
    assert got == [1]


async def test_emit_shortcut_builds_event():
    bus = EventBus()
    got = []
    bus.subscribe("*", lambda e: got.append(e))
    await bus.emit("device.offline", device_id="d")
    assert got[0].type == "device.offline"
    assert got[0].payload == {"device_id": "d"}
