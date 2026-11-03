"""HA protocol, nonblocking refresh, token budgets and the native Whisper boundary."""

import asyncio
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from aiohttp import web
from aiohttp.test_utils import TestServer

from wyoming_vulkan.config import ConfigError, EngineConfig, GpuConfig, HassConfig, load_config
from wyoming_vulkan.engines.whisper_cpp import FullParams, WhisperEngine
from wyoming_vulkan.hass_api import HomeAssistant, HomeAssistantError
from wyoming_vulkan.name_cache import HassNameCache
from wyoming_vulkan.vocabulary import RecognitionContext, clean_names


class VocabularyTests(unittest.TestCase):
    def test_priority_dedup_and_budget(self):
        context = RecognitionContext([" Office ", "Upstairs"], ["Nanit", " Baby monitor "],
                                     ["Garage"], ["Temperature", "office"])
        self.assertEqual(context.whisper_prompt(len, 32), "Office, Upstairs, Nanit.")
        self.assertEqual(context.all_names(), ["Office", "Upstairs", "Nanit", "Baby monitor", "Garage", "Temperature"])
        self.assertEqual(clean_names([None, " A\0 B ", "a b", "\t"]), ["A B"])

    def test_static_prefix_and_model_cache(self):
        context = RecognitionContext(["Office"])
        counter = Mock(side_effect=len)
        self.assertEqual(context.whisper_prompt(counter, 40, "Vocabulary", "medium"), "Vocabulary. Office.")
        calls = counter.call_count
        context.whisper_prompt(counter, 40, "Vocabulary", "medium")
        self.assertEqual(counter.call_count, calls)
        context.whisper_prompt(counter, 40, "Vocabulary", "turbo")
        self.assertGreater(counter.call_count, calls)
        with self.assertRaises(ValueError):
            context.whisper_prompt(len, 3, "too long")
        self.assertIsNone(RecognitionContext().whisper_prompt(len))


class ConfigTests(unittest.TestCase):
    def test_bounds_and_safe_url_errors(self):
        for kwargs in ({"timeout": 0}, {"refresh_seconds": -1}, {"timeout": float("nan")},
                       {"prompt_max_tokens": 224}, {"prompt_max_tokens": True},
                       {"api": "http://user:secret@ha/api"}, {"api": "http://ha/api?token=secret"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ConfigError) as err:
                HassConfig(**kwargs).validate()
            self.assertNotIn("secret", str(err.exception))

    def test_secret_file_precedence_and_no_config_secret(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "token"
            path.write_text("test-secret\n", encoding="utf-8")
            config = HassConfig(token_file=str(path))
            with patch.dict(os.environ, {"WYOMING_HASS_TOKEN": "other"}):
                self.assertEqual(config.read_token(), "test-secret")
            self.assertNotIn("test-secret", repr(config))
            path.unlink()
            with self.assertRaisesRegex(ConfigError, "Cannot read HA token file"):
                config.read_token()

    def test_toml(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.toml"
            path.write_text('[hass]\nprompt_max_tokens = 180\nrefresh_seconds = 0\n'
                            '[[stt]]\nname="w"\nbackend="whisper.cpp"\nmodel="medium.bin"\n')
            self.assertEqual(load_config(path).hass.prompt_max_tokens, 180)


RESULTS = {
    "homeassistant/expose_entity/list": {"exposed_entities": {
        "light.lamp": {"conversation": True}, "switch.disabled": {"conversation": True},
        "sensor.temp": {"conversation": True}, "light.private": {"conversation": False}}},
    "get_states": [{"entity_id": "light.lamp", "attributes": {"friendly_name": "Office Lamp"}},
                   {"entity_id": "light.private", "attributes": {"friendly_name": "Private"}}],
    "config/entity_registry/get_entries": {
        "light.lamp": {"name": "Lamp", "device_id": "device", "aliases": ["Desk Light"]},
        "switch.disabled": {"name": "Disabled", "disabled_by": "user", "area_id": "empty"},
        "sensor.temp": {"original_name": "Thermometer", "area_id": "office"}},
    "config/device_registry/list": [{"id": "device", "area_id": "office"}],
    "config/area_registry/list": [{"area_id": "office", "name": "Office", "aliases": ["Study"], "floor_id": "upper"},
                                  {"area_id": "empty", "name": "Garage"}],
    "config/floor_registry/list": [{"floor_id": "upper", "name": "Upstairs", "aliases": ["Top Floor"]}],
}


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.seen = []
        self.mode = "ok"
        self.received_auth = None
        async def handler(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.send_json({"type": "auth_required"})
            self.received_auth = await ws.receive_json()
            if self.mode == "auth":
                await ws.send_json({"type": "auth_invalid", "message": "test-secret"})
                return ws
            await ws.send_json({"type": "auth_ok"})
            async for raw in ws:
                import json
                message = json.loads(raw.data)
                self.seen.append(message)
                await ws.send_json({"id": message["id"] + (1 if self.mode == "id" else 0),
                                    "type": "result", "success": self.mode != "failure",
                                    "result": RESULTS[message["type"]], "error": "test-secret"})
            return ws
        app = web.Application()
        app.router.add_get("/api/websocket", handler)
        self.server = TestServer(app)
        await self.server.start_server()
        self.client = HomeAssistant("test-secret", str(self.server.make_url("/api")), timeout=1)

    async def asyncTearDown(self):
        await self.server.close()

    async def test_real_websocket_exposure_aliases_and_inherited_places(self):
        context = await self.client.get_context()
        self.assertEqual(self.received_auth, {"type": "auth", "access_token": "test-secret"})
        self.assertEqual(context.used_areas, ["Office", "Study", "Upstairs", "Top Floor"])
        self.assertEqual(context.priority_entities, ["Office Lamp", "Desk Light"])
        self.assertEqual(context.empty_areas, ["Garage"])
        self.assertEqual(context.other_entities, ["Thermometer"])
        request = next(m for m in self.seen if m["type"] == "config/entity_registry/get_entries")
        self.assertNotIn("light.private", request["entity_ids"])

    async def test_errors_never_surface_server_payloads(self):
        for mode in ("auth", "failure", "id"):
            self.mode = mode
            with self.subTest(mode=mode), self.assertRaises(HomeAssistantError) as err:
                await self.client.get_context()
            self.assertNotIn("test-secret", str(err.exception))

    async def test_timeout_covers_websocket_receives(self):
        async def slow(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.receive()
            return ws
        app = web.Application()
        app.router.add_get("/api/websocket", slow)
        async with TestServer(app) as server:
            client = HomeAssistant("test-secret", str(server.make_url("/api")), timeout=.03)
            with self.assertRaises(HomeAssistantError):
                await asyncio.wait_for(client.get_context(), .5)


class CacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_empty_snapshot_removes_old_names(self):
        async def fetch():
            return RecognitionContext()
        cache = HassNameCache(Mock(get_context=fetch))
        cache.context = RecognitionContext(["Removed Entity"])
        cache.schedule_refresh()
        await cache._task
        self.assertFalse(cache.context)
        await cache.close()

    async def test_single_flight_stale_failure_recovery_and_shutdown(self):
        gate = asyncio.Event()
        calls = 0
        fail = False
        async def fetch():
            nonlocal calls
            calls += 1
            await gate.wait()
            if fail:
                raise RuntimeError("test-secret")
            return RecognitionContext(["Office"])
        cache = HassNameCache(Mock(get_context=fetch), refresh_seconds=0)
        for _ in range(10):
            cache.schedule_refresh()
        await asyncio.sleep(0)
        self.assertEqual(calls, 1)
        self.assertFalse(cache.context)  # immediately usable while fetch is unfinished
        gate.set()
        await cache._task
        previous = cache.context
        fail = True
        with self.assertLogs("wyoming_vulkan.name_cache", level="WARNING") as logs:
            cache.schedule_refresh()
            await cache._task
        self.assertNotIn("test-secret", str(logs.output))
        self.assertIs(cache.context, previous)
        fail = False
        cache.schedule_refresh()
        await cache._task
        self.assertIs(cache.context, previous)  # unchanged snapshot keeps prompt memoization
        gate.clear()
        cache.schedule_refresh()
        await asyncio.sleep(0)
        await cache.close()
        self.assertTrue(cache._task.cancelled())

    async def test_throttle_failure_and_success(self):
        async def fetch():
            raise HomeAssistantError("unavailable")
        cache = HassNameCache(Mock(get_context=fetch), refresh_seconds=60)
        cache.schedule_refresh()
        await cache._task
        previous = cache._task
        cache.schedule_refresh()
        self.assertIs(cache._task, previous)
        await cache.close()


class WhisperTests(unittest.TestCase):
    def test_native_tokenizer_counts_utf8_space_and_model_cap(self):
        engine = WhisperEngine(EngineConfig("stt", "w", "whisper.cpp", Path("medium.bin")), GpuConfig())
        engine.ctx = 1
        engine.prompt_max_tokens = 8
        lib = Mock()
        lib.whisper_tokenize.side_effect = lambda ctx, data, tokens, capacity: -len(data)
        with patch("wyoming_vulkan.engines.whisper_cpp._lib", return_value=lib):
            self.assertEqual(engine._prompt(RecognitionContext(["Étage", "Nanit"]), 200), "Étage.")
            self.assertEqual(lib.whisper_tokenize.call_args.args[1], " Étage, Nanit.".encode())
            engine.config.options["initial_prompt"] = "Oversized prefix"
            with self.assertRaises(ValueError):
                engine._prompt(RecognitionContext(), 200)
        engine.ctx = None

    def test_medium_and_turbo_native_prompt_and_cleanup(self):
        for model in ("ggml-medium-q5_0.bin", "ggml-large-v3-turbo-q5_0.bin"):
            for rc in (0, -1):
                with self.subTest(model=model, rc=rc):
                    engine = WhisperEngine(EngineConfig("stt", model, "whisper.cpp", Path(model)), GpuConfig())
                    engine.ctx = 1
                    engine.params = FullParams()
                    engine.lock = threading.Lock()
                    engine.audio_ctx = 0
                    engine.max_seconds = None
                    engine.prompt_max_tokens = 223
                    engine.multilingual = False
                    engine._empty_vocabulary = RecognitionContext()
                    lib = Mock()
                    lib.whisper_tokenize.side_effect = lambda ctx, data, tokens, capacity: -len(data.decode())
                    observed = []
                    def full(ctx, params, samples, length):
                        observed.append(params.initial_prompt)
                        return rc
                    lib.whisper_full.side_effect = full
                    lib.whisper_full_n_segments.return_value = 0
                    with patch("wyoming_vulkan.engines.whisper_cpp._lib", return_value=lib):
                        if rc:
                            with self.assertRaises(RuntimeError):
                                engine.transcribe_with_vocabulary(np.zeros(1600), "en", RecognitionContext(["Étage", "Nanit"]), 200)
                        else:
                            engine.transcribe_with_vocabulary(np.zeros(1600), "en", RecognitionContext(["Étage", "Nanit"]), 200)
                            engine.transcribe(np.zeros(1600), "en")
                            self.assertIsNone(observed[-1])
                    self.assertEqual(observed[0], "Étage, Nanit.".encode())
                    self.assertIsNone(engine.params.initial_prompt)
                    engine.ctx = None


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_cache_never_blocks_whisper_or_parakeet_endpoints(self):
        from functools import partial
        from wyoming.asr import Transcript
        from wyoming.audio import AudioChunk, AudioStart, AudioStop
        from wyoming.client import AsyncTcpClient
        from wyoming.server import AsyncTcpServer
        from wyoming_vulkan.config import ServerConfig
        from wyoming_vulkan.handler import Services, WyomingHandler
        from test_units import FakeStt, free_port

        gate = asyncio.Event()
        calls = 0
        async def fetch():
            nonlocal calls
            calls += 1
            await gate.wait()
            return RecognitionContext(["New Name"])
        names = HassNameCache(Mock(get_context=fetch))
        names.context = RecognitionContext(["Cached Name"])
        engines = [FakeStt("medium"), FakeStt("turbo"), FakeStt("parakeet")]
        observed = []
        for engine in engines[:2]:
            def transcribe(audio, language, context, budget, engine=engine):
                observed.append((engine.name, context.all_names(), budget))
                return "heard"
            engine.transcribe_with_vocabulary = transcribe
        servers = []
        ports = []
        try:
            for engine in engines:
                port = free_port()
                server = AsyncTcpServer("127.0.0.1", port)
                await server.start(partial(WyomingHandler, Services(ServerConfig(), [engine], None, names=names)))
                servers.append(server)
                ports.append(port)
            async def request(port):
                async with AsyncTcpClient("127.0.0.1", port) as client:
                    await client.write_event(AudioStart(rate=16000, width=2, channels=1).event())
                    await client.write_event(AudioChunk(audio=b"\0\0" * 1600, rate=16000, width=2, channels=1).event())
                    await client.write_event(AudioStop().event())
                    event = await asyncio.wait_for(client.read_event(), 1)
                    self.assertTrue(Transcript.is_type(event.type))
            await asyncio.gather(*(request(port) for port in ports))
            self.assertEqual(calls, 1)
            self.assertFalse(gate.is_set())
            self.assertCountEqual(observed, [("medium", ["Cached Name"], 200), ("turbo", ["Cached Name"], 200)])
            self.assertEqual(len(engines[2].calls), 1)
        finally:
            for server in servers:
                await server.stop()
            await names.close()


if __name__ == "__main__":
    unittest.main()
