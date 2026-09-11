"""CharacterHost wires the engine to the event bus without the engine knowing about it."""
from datetime import datetime, timedelta

import pytest

from heren_core.bus import EventBus
from heren_core.character import CharacterConfig
from heren_core.character_host import CharacterHost


class Clock:
    def __init__(self, hhmm="14:00"):
        h, m = map(int, hhmm.split(":"))
        self.dt = datetime(2026, 9, 10, h, m)

    def now(self):
        return self.dt

    def advance(self, s):
        self.dt += timedelta(seconds=s)


@pytest.fixture
def host():
    bus = EventBus()
    clk = Clock("14:00")
    out = []
    bus.subscribe("character.state", lambda e: out.append(e.payload))
    h = CharacterHost(bus=bus, cfg=CharacterConfig(reaction_duration_s=3), now=clk.now)
    h.attach()
    return h, bus, clk, out


async def test_bus_events_drive_the_engine(host):
    h, bus, clk, out = host
    await bus.emit("hermes.thinking")
    assert h.engine.state().activity == "thinking"
    await bus.emit("hermes.tool.started", name="terminal")
    assert h.engine.state().activity == "working"
    await bus.emit("hermes.tool.completed", name="terminal")
    await bus.emit("hermes.speaking")
    assert h.engine.state().activity == "speaking"
    await bus.emit("hermes.done")
    assert h.engine.state().activity == "idle"


async def test_action_and_approval_events_map_to_mood_and_attention(host):
    h, bus, clk, out = host
    await bus.emit("ui.approval.needed", request_id="r1")
    assert h.engine.state().attention == "notification"
    await bus.emit("ui.approval.resolved", request_id="r1", approved=True)
    await bus.emit("device.action.completed", request_id="r1")
    assert h.engine.state().mood == "happy"
    await bus.emit("device.offline", device_id="x")
    assert h.engine.state().mood == "annoyed"


async def test_state_is_published_only_when_it_changes(host):
    h, bus, clk, out = host
    await h.publish_if_changed()
    n = len(out)
    await h.publish_if_changed()
    assert len(out) == n  # unchanged
    await bus.emit("character.touch")
    await h.publish_if_changed()
    assert len(out) == n + 1 and out[-1]["activity"] == "listening"


async def test_character_events_do_not_feed_back_into_the_engine(host):
    h, bus, clk, out = host
    # the host publishes character.state; it must ignore its own output
    await bus.emit("character.state", activity="sleeping", mood="sleepy")
    assert h.engine.state().activity == "idle"


async def test_snapshot_dict_matches_engine(host):
    h, *_ = host
    d = h.snapshot()
    assert d["activity"] == "idle" and d["mood"] == "neutral" and d["energy"] == 1.0


async def test_voice_playback_events_extend_speaking(host):
    h, bus, clk, out = host
    await bus.emit("hermes.speaking")
    await bus.emit("voice.playback.started", clip_id="c1")
    await bus.emit("hermes.done")
    assert h.engine.state().activity == "speaking"
    await bus.emit("voice.playback.finished")
    assert h.engine.state().activity == "idle"


async def test_host_persists_on_change_and_restores_on_attach():
    saved = {}
    async def save(d): saved.update(d)
    async def load(): return dict(saved) if saved else None
    bus = EventBus(); clk = Clock("23:30")
    h = CharacterHost(bus=bus, cfg=CharacterConfig(), now=clk.now, save_state=save, load_state=load)
    h.attach(); await h.restore()
    await bus.emit("hermes.speaking"); await bus.emit("hermes.done")
    assert saved and saved["energy"] < 1.0, "state change → saved"
    # new host (restart) picks it up
    h2 = CharacterHost(bus=EventBus(), cfg=CharacterConfig(), now=Clock("23:31").now, save_state=save, load_state=load)
    await h2.restore()
    assert h2.engine.export_state()["energy"] == saved["energy"]
    assert h2.engine.export_state()["debt"] == saved["debt"]


async def test_host_without_persistence_still_works():
    bus = EventBus(); clk = Clock("14:00")
    h = CharacterHost(bus=bus, cfg=CharacterConfig(), now=clk.now)
    h.attach(); await h.restore()
    await bus.emit("hermes.thinking")
    assert h.engine.state().activity == "thinking"
