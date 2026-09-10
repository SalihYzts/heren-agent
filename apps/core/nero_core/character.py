"""Character engine — a deterministic state machine with an injected clock.

Four independent layers:
    Activity   idle | listening | thinking | speaking | working | sleeping | waking
    Mood       neutral | happy | sleepy | annoyed | confused
    Attention  none | user | notification | device
    Energy     0.0 … 1.0

Rules (all tunables in CharacterConfig):
  * "night" = [sleep_start, wake_time); "deep night" = [deep_sleep_start, wake_time)
  * mood is sleepy whenever it is night, energy is low, or there is sleep debt
  * idle for sleep_after_idle_s at night (deep_sleep_after_idle_s in deep night) → sleeping
  * touch / wake word: sleeping → waking (waking_duration_s) → listening; else → listening
  * listening times out to idle
  * thinking / working / speaking are driven by the assistant lifecycle; working = tools in flight
  * reactions (happy / confused / annoyed, device attention) last reaction_duration_s
  * approvals pending → attention = notification
  * night interactions cost energy and add sleep debt; debt clears at debt_clear_time
  * energy recovers while sleeping (sleep_recovery_per_min) and slowly while idle by day

Sleeping is presentation only: every method still works while asleep; nothing here
blocks, schedules, or touches I/O. `tick()` must be called periodically (host does it).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from enum import StrEnum
from typing import Any


class Activity(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    WORKING = "working"
    SLEEPING = "sleeping"
    WAKING = "waking"


class Mood(StrEnum):
    NEUTRAL = "neutral"
    HAPPY = "happy"
    SLEEPY = "sleepy"
    ANNOYED = "annoyed"
    CONFUSED = "confused"


class Attention(StrEnum):
    NONE = "none"
    USER = "user"
    NOTIFICATION = "notification"
    DEVICE = "device"


def _hhmm(s: str) -> dtime:
    h, m = s.split(":")
    return dtime(int(h), int(m))


@dataclass(frozen=True)
class CharacterConfig:
    sleep_start: str = "23:00"
    deep_sleep_start: str = "00:00"
    wake_time: str = "07:00"
    sleep_after_idle_s: float = 600.0
    deep_sleep_after_idle_s: float = 120.0
    waking_duration_s: float = 2.0
    listen_timeout_s: float = 8.0
    reaction_duration_s: float = 3.0
    night_interaction_cost: float = 0.05
    debt_threshold: float = 0.2
    debt_clear_time: str = "12:00"
    sleep_recovery_per_min: float = 0.02
    idle_recovery_per_min: float = 0.005
    low_energy: float = 0.35
    max_step_s: float = 60.0  # integration granularity for large clock jumps


@dataclass(frozen=True)
class CharacterState:
    activity: Activity
    mood: Mood
    attention: Attention
    energy: float
    schema: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "activity": self.activity, "mood": self.mood,
                "attention": self.attention, "energy": round(self.energy, 3)}


@dataclass
class _Reaction:
    mood: Mood | None
    attention: Attention | None
    until: float


class CharacterEngine:
    def __init__(self, cfg: CharacterConfig | None = None, *, now: Callable[[], datetime]) -> None:
        self.cfg = cfg or CharacterConfig()
        self._now = now
        t = self._t()
        self._activity = Activity.IDLE
        self._energy = 1.0
        self._debt = 0.0
        self._last_interaction = t
        self._last_tick = t
        self._waking_until = 0.0
        self._listening_until = 0.0
        self._tools_running = 0
        self._pending_approvals = 0
        self._reaction: _Reaction | None = None
        self._user_attention = False
        self._last_state = self._compute()

    # ----------------------------------------------------------------- clock helpers

    def _t(self) -> float:
        return self._now().timestamp()

    def _clock(self) -> dtime:
        return self._now().time()

    @staticmethod
    def _in_window(now: dtime, start: dtime, end: dtime) -> bool:
        return start <= now < end if start <= end else (now >= start or now < end)

    def _is_night(self) -> bool:
        return self._in_window(self._clock(), _hhmm(self.cfg.sleep_start), _hhmm(self.cfg.wake_time))

    def _is_deep_night(self) -> bool:
        return self._in_window(self._clock(), _hhmm(self.cfg.deep_sleep_start), _hhmm(self.cfg.wake_time))

    # ----------------------------------------------------------------- inputs

    def touch(self) -> None:
        self._interact()
        self._user_attention = True
        if self._activity == Activity.SLEEPING:
            self._activity = Activity.WAKING
            self._waking_until = self._t() + self.cfg.waking_duration_s
        elif self._activity in (Activity.IDLE, Activity.LISTENING):
            self._listen()

    def wake_word(self) -> None:
        self.touch()

    def assistant_thinking(self) -> None:
        self._interact()
        self._user_attention = True
        self._activity = Activity.THINKING

    def tool_started(self) -> None:
        self._tools_running += 1
        if self._activity not in (Activity.SLEEPING, Activity.WAKING):
            self._activity = Activity.WORKING

    def tool_finished(self) -> None:
        self._tools_running = max(0, self._tools_running - 1)
        if self._activity == Activity.WORKING and self._tools_running == 0:
            self._activity = Activity.THINKING

    def tool_failed(self) -> None:
        self.tool_finished()
        self._react(Mood.CONFUSED, None)

    def assistant_speaking(self) -> None:
        self._interact()
        self._activity = Activity.SPEAKING
        if self._is_night():
            self._energy = max(0.0, self._energy - self.cfg.night_interaction_cost)
            self._debt += self.cfg.night_interaction_cost

    def assistant_done(self) -> None:
        self._tools_running = 0
        self._user_attention = False
        self._activity = Activity.IDLE
        self._last_interaction = self._t()

    def device_action_completed(self) -> None:
        if self._activity != Activity.SLEEPING:
            self._react(Mood.HAPPY, None)

    def device_offline(self) -> None:
        self._react(Mood.ANNOYED, Attention.DEVICE)

    def approval_needed(self) -> None:
        self._pending_approvals += 1

    def approval_resolved(self) -> None:
        self._pending_approvals = max(0, self._pending_approvals - 1)

    # ----------------------------------------------------------------- internals

    def _interact(self) -> None:
        self._last_interaction = self._t()

    def _listen(self) -> None:
        self._activity = Activity.LISTENING
        self._listening_until = self._t() + self.cfg.listen_timeout_s

    def _react(self, mood: Mood | None, attention: Attention | None) -> None:
        self._reaction = _Reaction(mood, attention, self._t() + self.cfg.reaction_duration_s)

    def tick(self) -> bool:
        """Advance time-driven transitions. Returns True if the visible state changed.

        Large gaps (host paused, test clock jumps) are integrated in bounded steps so
        energy accounting depends only on wall time, not on how often tick() is called.
        """
        target = self._t()
        before = self._last_state
        while True:
            step_end = min(target, self._last_tick + self.cfg.max_step_s)
            self._step(step_end)
            if step_end >= target:
                break
        new = self._compute()
        self._last_state = new
        return new != before

    def _step(self, t: float) -> None:
        dt_min = max(0.0, t - self._last_tick) / 60.0
        self._last_tick = t
        clock = (self._now().__class__.fromtimestamp(t)).time()

        if self._reaction and t >= self._reaction.until:
            self._reaction = None

        if self._activity == Activity.WAKING and t >= self._waking_until:
            self._listen()
        elif self._activity == Activity.LISTENING and t >= self._listening_until:
            self._activity = Activity.IDLE
            self._user_attention = False
            self._last_interaction = t
        elif self._activity == Activity.IDLE:
            idle_for = t - self._last_interaction
            if self._in_window(clock, _hhmm(self.cfg.deep_sleep_start), _hhmm(self.cfg.wake_time)) \
                    and idle_for >= self.cfg.deep_sleep_after_idle_s:
                self._activity = Activity.SLEEPING
            elif self._in_window(clock, _hhmm(self.cfg.sleep_start), _hhmm(self.cfg.wake_time)) \
                    and idle_for >= self.cfg.sleep_after_idle_s:
                self._activity = Activity.SLEEPING

        night = self._in_window(clock, _hhmm(self.cfg.sleep_start), _hhmm(self.cfg.wake_time))
        if self._activity == Activity.SLEEPING and not night:
            # morning: wake up quietly into idle (no listening — nobody called)
            self._activity = Activity.IDLE
            self._last_interaction = t
        if self._activity == Activity.SLEEPING:
            self._energy = min(1.0, self._energy + self.cfg.sleep_recovery_per_min * dt_min)
        elif self._activity == Activity.IDLE and not night:
            self._energy = min(1.0, self._energy + self.cfg.idle_recovery_per_min * dt_min)

        if self._debt and self._in_window(clock, _hhmm(self.cfg.debt_clear_time), _hhmm(self.cfg.sleep_start)):
            self._debt = 0.0

    def _compute(self) -> CharacterState:
        night = self._is_night()
        sleepy = night or self._energy < self.cfg.low_energy or self._debt >= self.cfg.debt_threshold

        mood = Mood.SLEEPY if sleepy else Mood.NEUTRAL
        if self._reaction and self._reaction.mood and self._activity != Activity.SLEEPING:
            mood = self._reaction.mood

        if self._pending_approvals > 0:
            attention = Attention.NOTIFICATION
        elif self._reaction and self._reaction.attention:
            attention = self._reaction.attention
        elif self._user_attention or self._activity in (Activity.LISTENING, Activity.WAKING,
                                                        Activity.THINKING, Activity.SPEAKING):
            attention = Attention.USER
        else:
            attention = Attention.NONE

        return CharacterState(self._activity, mood, attention, self._energy)

    def state(self) -> CharacterState:
        return self._compute()
