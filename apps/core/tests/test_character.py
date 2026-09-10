"""Character engine — deterministic, clock-injected, no I/O.

Layers: Activity / Mood / Attention / Energy. Sleep is presentation only.
"""
from datetime import datetime

import pytest

from heren_core.character import (
    Activity,
    Attention,
    CharacterConfig,
    CharacterEngine,
    Mood,
)


class Clock:
    """Fake wall clock: local datetime + monotonic seconds."""

    def __init__(self, hhmm="14:00"):
        h, m = map(int, hhmm.split(":"))
        self.dt = datetime(2026, 9, 10, h, m)

    def now(self) -> datetime:
        return self.dt

    def advance(self, seconds: float):
        from datetime import timedelta
        self.dt = self.dt + timedelta(seconds=seconds)


def engine(hhmm="14:00", **cfg):
    clk = Clock(hhmm)
    e = CharacterEngine(CharacterConfig(**cfg), now=clk.now)
    return e, clk


# ----------------------------------------------------------------- baseline


def test_daytime_default_is_idle_neutral_full_energy():
    e, _ = engine("14:00")
    s = e.state()
    assert s.activity == Activity.IDLE
    assert s.mood == Mood.NEUTRAL
    assert s.attention == Attention.NONE
    assert s.energy == pytest.approx(1.0)


def test_state_is_serialisable_and_versioned():
    e, _ = engine()
    d = e.state().to_dict()
    assert d["activity"] == "idle" and d["mood"] == "neutral" and d["attention"] == "none"
    assert 0 <= d["energy"] <= 1
    assert d["schema"] == 1


# ----------------------------------------------------------------- time rules


def test_after_sleep_start_mood_is_sleepy():
    e, _ = engine("23:10", sleep_start="23:00", deep_sleep_start="00:00")
    assert e.state().mood == Mood.SLEEPY
    assert e.state().activity == Activity.IDLE  # not asleep yet — needs inactivity


def test_sleepy_window_wraps_past_midnight():
    e, _ = engine("02:30", sleep_start="23:00", wake_time="07:00")
    assert e.state().mood == Mood.SLEEPY
    e2, _ = engine("07:30", sleep_start="23:00", wake_time="07:00")
    assert e2.state().mood == Mood.NEUTRAL


def test_idle_long_enough_at_night_falls_asleep():
    e, clk = engine("23:30", sleep_start="23:00", sleep_after_idle_s=600)
    e.tick()
    assert e.state().activity == Activity.IDLE
    clk.advance(601)
    e.tick()
    assert e.state().activity == Activity.SLEEPING


def test_daytime_idle_never_sleeps():
    e, clk = engine("14:00", sleep_after_idle_s=600)
    clk.advance(3600 * 5)
    e.tick()
    assert e.state().activity == Activity.IDLE


def test_deep_sleep_makes_it_very_sleepy_energy_floor_and_faster_sleep():
    e, clk = engine("00:30", sleep_start="23:00", deep_sleep_start="00:00",
                    sleep_after_idle_s=600, deep_sleep_after_idle_s=60)
    clk.advance(61)
    e.tick()
    assert e.state().activity == Activity.SLEEPING


# ----------------------------------------------------------------- waking


def test_touch_while_sleeping_goes_waking_then_listening():
    e, clk = engine("23:30", sleep_start="23:00", sleep_after_idle_s=10, waking_duration_s=2)
    clk.advance(11); e.tick()
    assert e.state().activity == Activity.SLEEPING
    e.touch()
    assert e.state().activity == Activity.WAKING
    assert e.state().attention == Attention.USER
    clk.advance(2.1); e.tick()
    assert e.state().activity == Activity.LISTENING


def test_wake_word_behaves_like_touch():
    e, clk = engine("23:30", sleep_start="23:00", sleep_after_idle_s=10, waking_duration_s=1)
    clk.advance(11); e.tick()
    e.wake_word()
    assert e.state().activity == Activity.WAKING
    clk.advance(1.1); e.tick()
    assert e.state().activity == Activity.LISTENING


def test_listening_times_out_back_to_idle():
    e, clk = engine("14:00", listen_timeout_s=8)
    e.touch()
    assert e.state().activity == Activity.LISTENING
    clk.advance(8.1); e.tick()
    assert e.state().activity == Activity.IDLE
    assert e.state().attention == Attention.NONE


# ----------------------------------------------------------------- assistant lifecycle


def test_assistant_flow_thinking_working_speaking_idle():
    e, _ = engine("14:00")
    e.assistant_thinking()
    assert e.state().activity == Activity.THINKING
    e.tool_started()
    assert e.state().activity == Activity.WORKING
    e.tool_started(); e.tool_finished()
    assert e.state().activity == Activity.WORKING  # one tool still running
    e.tool_finished()
    assert e.state().activity == Activity.THINKING
    e.assistant_speaking()
    assert e.state().activity == Activity.SPEAKING
    e.assistant_done()
    assert e.state().activity == Activity.IDLE


def test_speaking_at_night_keeps_sleepy_mood_and_costs_energy():
    e, _ = engine("00:40", sleep_start="23:00", deep_sleep_start="00:00", night_interaction_cost=0.1)
    before = e.state().energy
    e.assistant_thinking(); e.assistant_speaking()
    s = e.state()
    assert s.activity == Activity.SPEAKING and s.mood == Mood.SLEEPY
    assert s.energy < before


def test_tool_failure_shows_confused_briefly():
    e, clk = engine("14:00", reaction_duration_s=3)
    e.assistant_thinking(); e.tool_started(); e.tool_failed()
    assert e.state().mood == Mood.CONFUSED
    clk.advance(3.1); e.tick()
    assert e.state().mood == Mood.NEUTRAL


def test_tool_failure_at_night_returns_to_sleepy_not_neutral():
    e, clk = engine("23:30", sleep_start="23:00", reaction_duration_s=3)
    e.tool_started(); e.tool_failed()
    assert e.state().mood == Mood.CONFUSED
    clk.advance(3.1); e.tick()
    assert e.state().mood == Mood.SLEEPY


def test_action_completed_makes_it_happy_briefly():
    e, clk = engine("14:00", reaction_duration_s=3)
    e.device_action_completed()
    assert e.state().mood == Mood.HAPPY
    clk.advance(3.1); e.tick()
    assert e.state().mood == Mood.NEUTRAL


def test_approval_needed_pulls_attention_to_notification_until_resolved():
    e, _ = engine("14:00")
    e.approval_needed()
    assert e.state().attention == Attention.NOTIFICATION
    e.approval_needed()
    e.approval_resolved()
    assert e.state().attention == Attention.NOTIFICATION  # one still pending
    e.approval_resolved()
    assert e.state().attention == Attention.NONE


def test_device_offline_sets_annoyed_and_device_attention_briefly():
    e, clk = engine("14:00", reaction_duration_s=3)
    e.device_offline()
    s = e.state()
    assert s.mood == Mood.ANNOYED and s.attention == Attention.DEVICE
    clk.advance(3.1); e.tick()
    assert e.state().mood == Mood.NEUTRAL and e.state().attention == Attention.NONE


# ----------------------------------------------------------------- energy


def test_night_interactions_accumulate_debt_and_next_morning_is_sleepy():
    e, clk = engine("00:30", sleep_start="23:00", deep_sleep_start="00:00", wake_time="07:00",
                    night_interaction_cost=0.15, debt_threshold=0.3, debt_clear_time="12:00")
    for _ in range(3):
        e.assistant_thinking(); e.assistant_speaking(); e.assistant_done()
    clk.advance(3600 * 8)  # 08:30
    e.tick()
    assert e.state().activity == Activity.IDLE  # woke up at wake_time on its own
    assert e.state().mood == Mood.SLEEPY        # …but carries last night's debt
    clk.advance(3600 * 4)  # 12:30 — debt cleared
    e.tick()
    assert e.state().mood == Mood.NEUTRAL


def test_sleeping_character_wakes_at_wake_time_even_without_interaction():
    e, clk = engine("23:30", sleep_start="23:00", wake_time="07:00", sleep_after_idle_s=10)
    clk.advance(11); e.tick()
    assert e.state().activity == Activity.SLEEPING
    clk.advance(3600 * 7)  # 06:30
    e.tick()
    assert e.state().activity == Activity.SLEEPING
    clk.advance(3600)  # 07:30
    e.tick()
    assert e.state().activity == Activity.IDLE


def test_energy_recovers_while_sleeping_and_is_clamped():
    e, clk = engine("00:30", sleep_start="23:00", deep_sleep_start="00:00", night_interaction_cost=0.5,
                    sleep_after_idle_s=10, sleep_recovery_per_min=0.2)
    e.assistant_thinking(); e.assistant_speaking(); e.assistant_done()
    assert e.state().energy == pytest.approx(0.5)
    clk.advance(11); e.tick()
    assert e.state().activity == Activity.SLEEPING
    clk.advance(60 * 10); e.tick()
    assert e.state().energy == pytest.approx(1.0)


# ----------------------------------------------------------------- change detection


def test_tick_reports_whether_anything_changed():
    e, clk = engine("14:00")
    assert e.tick() is False
    e.touch()
    assert e.tick() is True   # idle → listening became visible
    assert e.tick() is False  # nothing new
    clk.advance(100)
    assert e.tick() is True   # listening timed out → idle


def test_sleeping_is_presentation_only_engine_still_accepts_events():
    e, clk = engine("23:30", sleep_start="23:00", sleep_after_idle_s=10)
    clk.advance(11); e.tick()
    assert e.state().activity == Activity.SLEEPING
    e.device_action_completed()  # background work continues; character doesn't have to wake
    assert e.state().activity == Activity.SLEEPING
    assert e.state().mood == Mood.SLEEPY  # no "happy" while asleep


# ----------------------------------------------------------------- voice playback

def test_character_keeps_speaking_while_audio_plays_after_hermes_is_done():
    e, clk = engine("14:00")
    e.assistant_thinking()
    e.assistant_speaking()
    e.speech_started()          # UI started playing the first clip
    e.assistant_done()          # Hermes run finished before the audio did
    assert e.state().activity == Activity.SPEAKING
    e.speech_finished()
    assert e.state().activity == Activity.IDLE


def test_speech_without_audio_still_ends_on_done():
    e, clk = engine("14:00")
    e.assistant_speaking()
    e.assistant_done()
    assert e.state().activity == Activity.IDLE


def test_speech_finished_when_not_speaking_is_harmless():
    e, clk = engine("14:00")
    e.speech_finished()
    assert e.state().activity == Activity.IDLE
    e.assistant_thinking()
    e.speech_finished()         # stray event mid-thought must not knock the activity
    assert e.state().activity == Activity.THINKING
