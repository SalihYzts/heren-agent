"""VoiceHost — the bus side of voice.

Inbound:
    hermes.text {run_id, text}      → queued; synthesized in order in a worker thread
    voice.interrupt {run_id?}       → drop everything pending (barge-in / user pressed stop)
Outbound:
    voice.speech {run_id, seq, clip_id, url, text, duration_s}   one per sentence, in order
    voice.stopped {run_id}          after an interrupt
    voice.error {run_id, text, error}
    voice.transcript {text, language, confidence}   from transcribe()

Clips live in a bounded in-memory store; the HTTP layer serves them by id.
The character is only *read* (mood/energy → prosody); the engine stays pure.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from heren_core.bus import EventBus
from heren_core.protocol import Event
from heren_core.voice.providers import AudioClip, STTProvider, Transcript, TTSProvider, prosody_for

log = logging.getLogger("heren.voice")


@dataclass
class _Job:
    run_id: str
    seq: int
    text: str
    generation: int


class VoiceHost:
    def __init__(self, *, bus: EventBus, tts: TTSProvider, stt: STTProvider,
                 character_state: Callable[[], dict[str, Any]], language: str = "tr",
                 url_prefix: str = "/api/voice/audio/", max_clips: int = 64) -> None:
        self.bus = bus
        self.tts = tts
        self.stt = stt
        self.character_state = character_state
        self.language = language
        self.url_prefix = url_prefix
        self.max_clips = max_clips
        self._clips: OrderedDict[str, AudioClip] = OrderedDict()
        self._queue: asyncio.Queue[_Job] = asyncio.Queue()
        self._seq: dict[str, int] = {}
        self._generation = 0          # bumped on interrupt; stale jobs are skipped
        self._worker: asyncio.Task[None] | None = None
        self._unsub: Callable[[], None] | None = None
        self._idle = asyncio.Event()
        self._idle.set()

    # ------------------------------------------------------------ wiring

    def attach(self) -> None:
        self._unsub = self.bus.subscribe("*", self._on_event)

    def detach(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    async def stop(self) -> None:
        self.detach()
        if self._worker:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None

    async def _on_event(self, e: Event) -> None:
        if e.type == "hermes.text":
            text = str(e.payload.get("text") or "").strip()
            if not text:
                return
            run_id = str(e.payload.get("run_id") or "")
            seq = self._seq.get(run_id, 0)
            self._seq[run_id] = seq + 1
            self._queue.put_nowait(_Job(run_id, seq, text, self._generation))
            self._idle.clear()
            self._ensure_worker()
        elif e.type == "voice.interrupt":
            await self._interrupt(str(e.payload.get("run_id") or ""))

    # ------------------------------------------------------------ queue

    def _ensure_worker(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while True:
            if self._queue.empty():
                self._idle.set()
            job = await self._queue.get()
            if job.generation != self._generation:
                continue  # dropped by interrupt
            try:
                st = self.character_state() or {}
                prosody = prosody_for(str(st.get("mood", "neutral")), float(st.get("energy", 1.0)))
                clip = await asyncio.to_thread(self.tts.synthesize, job.text, prosody)
            except Exception as ex:
                log.exception("tts failed")
                await self.bus.emit("voice.error", run_id=job.run_id, text=job.text, error=str(ex))
                continue
            if job.generation != self._generation:
                continue  # interrupted while synthesizing: never announce it
            clip_id = secrets.token_urlsafe(8)
            self._clips[clip_id] = clip
            while len(self._clips) > self.max_clips:
                self._clips.popitem(last=False)
            await self.bus.emit("voice.speech", run_id=job.run_id, seq=job.seq, clip_id=clip_id,
                                url=f"{self.url_prefix}{clip_id}.wav", text=job.text,
                                duration_s=clip.duration_s)

    async def _interrupt(self, run_id: str) -> None:
        self._generation += 1
        while not self._queue.empty():
            self._queue.get_nowait()
        self._seq.clear()
        await self.bus.emit("voice.stopped", run_id=run_id)

    async def drain(self) -> None:
        """Wait until every queued sentence is synthesized (tests / graceful shutdown)."""
        if self._worker is None:
            return
        while not (self._queue.empty() and self._idle.is_set()):
            await asyncio.sleep(0.005)
        # the worker may still be inside a synthesize call for the last job: idle is set
        # only when it loops back to an empty queue, so this is exact.

    # ------------------------------------------------------------ clips / stt

    def clip(self, clip_id: str) -> AudioClip | None:
        return self._clips.get(clip_id)

    async def transcribe(self, wav: bytes, language: str | None = None) -> Transcript:
        t = await asyncio.to_thread(self.stt.transcribe, wav, language or self.language)
        await self.bus.emit("voice.transcript", text=t.text, language=t.language, confidence=t.confidence)
        return t
