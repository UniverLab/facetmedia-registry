"""Clip-cache behaviour for the voicestudio runner (speak and clone)."""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

from test_voicestudio_cycle import (
    BAD_HEARD,
    CLONE_ID,
    CLONE_PROFILES,
    MAX_TRIES,
    PACKAGE,
    RATE_HZ,
    SEED,
    TEXT,
    _backend,
    _piece_request,
    _read_lines,
    _result,
    _stub_dir,
)

DROPOUT_MAX_MS = 200.0


@dataclass(frozen=True)
class _RunVS:
    capability: str = "voicestudio.speak"
    model: str = "voxcpm2"
    voice: str = "narradora"
    profiles: list[dict[str, str]] | None = None
    extra_inputs: dict[str, object] | None = None


def _vs_cache_key(
    model: str,
    voice: str,
    text: str,
    language: str,
    num_step: int | None,
    guidance_scale: float | None,
    seed: int,
) -> str:
    payload = {
        "guidance_scale": guidance_scale,
        "language": language,
        "model": model,
        "num_step": num_step,
        "seed": int(seed),
        "text": text,
        "tool_version": "c2ef998",
        "voice": voice,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _write_tone_wav(path: Path, frames: int, rate: int = RATE_HZ) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        data = bytearray()
        for i in range(frames):
            value = int(12000 * math.sin(2 * math.pi * 220 * i / rate))
            data += struct.pack("<h", value)
        writer.writeframes(bytes(data))


def _write_dropout_wav(path: Path, frames: int, rate: int = RATE_HZ) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    start_zero = int(frames * 0.3)
    end_zero = start_zero + int(0.3 * rate)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        data = bytearray()
        for i in range(frames):
            if start_zero <= i < end_zero < frames - rate // 10:
                value = 0
            else:
                value = int(12000 * math.sin(2 * math.pi * 220 * i / rate))
            data += struct.pack("<h", value)
        writer.writeframes(bytes(data))


def _run_vs(
    tmp_path: Path,
    states: list[str],
    heard: list[str],
    *,
    facet_home: Path,
    spec: _RunVS | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Path]]:
    spec = spec or _RunVS()
    result_path = _piece_request(
        tmp_path, spec.model, spec.capability, spec.voice, spec.extra_inputs
    )
    stub_dir = _stub_dir(tmp_path)
    calls = tmp_path / "whisper-calls.jsonl"
    calls.touch()
    process, url, files = _backend(tmp_path, states, profiles=spec.profiles)
    try:
        env = {
            **os.environ,
            "PYTHONPATH": str(stub_dir),
            "FACET_SERVER_URL": url,
            "STUB_CALLS": str(calls),
            "STUB_HEARD": json.dumps(heard),
            "FACET_HOME": str(facet_home),
        }
        done = subprocess.run(
            [
                sys.executable,
                str(PACKAGE / "runner.py"),
                "run",
                "--input",
                str(tmp_path / "run-request.json"),
                "--result",
                str(result_path),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        return done, files
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_run_cache_hit_skips_post_but_transcribes(tmp_path: Path) -> None:
    facet_home = tmp_path / "home"
    key = _vs_cache_key("voxcpm2", "narradora", TEXT, "es", None, None, SEED)
    cache_wav = facet_home / "data" / "voicestudio" / "clip-cache" / f"{key}.wav"
    _write_tone_wav(cache_wav, int(RATE_HZ * 2.5))
    done, files = _run_vs(tmp_path, ["ready"], [TEXT], facet_home=facet_home)
    assert done.returncode == 0, done.stdout + done.stderr
    result = _result(tmp_path / "run-result.json")
    asset = result["assets"][0]
    assert asset["properties"]["cached"] is True
    assert asset["seed"] == SEED
    bodies = _read_lines(files["bod"])
    assert bodies == []
    calls = _read_lines(tmp_path / "whisper-calls.jsonl")
    assert any(c.get("call") == "transcribe" for c in calls)


def test_run_failed_final_not_cached(tmp_path: Path) -> None:
    facet_home = tmp_path / "home"
    done, _files = _run_vs(tmp_path, ["ready"], [BAD_HEARD] * MAX_TRIES, facet_home=facet_home)
    assert done.returncode == 0, done.stdout + done.stderr
    cache_dir = facet_home / "data" / "voicestudio" / "clip-cache"
    cached = list(cache_dir.glob("*.wav")) if cache_dir.exists() else []
    assert cached == []


def test_clone_cache_honored(tmp_path: Path) -> None:
    facet_home = tmp_path / "home"
    key = _vs_cache_key("cosyvoice", CLONE_ID, TEXT, "es", None, None, SEED)
    cache_wav = facet_home / "data" / "voicestudio" / "clip-cache" / f"{key}.wav"
    _write_tone_wav(cache_wav, int(RATE_HZ * 2.5))
    done, files = _run_vs(
        tmp_path,
        ["ready"],
        [TEXT],
        facet_home=facet_home,
        spec=_RunVS(
            capability="voicestudio.clone",
            model="cosyvoice",
            voice=CLONE_ID,
            profiles=CLONE_PROFILES,
        ),
    )
    assert done.returncode == 0, done.stdout + done.stderr
    result = _result(tmp_path / "run-result.json")
    asset = result["assets"][0]
    assert asset["properties"]["cached"] is True
    assert asset["properties"]["model"] == "cosyvoice"
    assert _read_lines(files["bod"]) == []


def test_verify_dropout_fails(tmp_path: Path) -> None:
    out = tmp_path / "out-vd"
    out.mkdir()
    stub_dir = _stub_dir(tmp_path)
    wav_path = out / "intro.wav"
    _write_dropout_wav(wav_path, int(RATE_HZ * 2.5))
    model_dir = tmp_path / "mw"
    model_dir.mkdir()
    (model_dir / "faster-whisper-small").mkdir()
    inputs = {
        "voice": "narradora",
        "model": "voxcpm2",
        "language": "es",
        "clip": [{"name": "intro", "text": TEXT, "seed": SEED}],
    }
    request = {
        "protocol": 1,
        "verb": "verify",
        "capability": "voicestudio.speak",
        "inputs": inputs,
        "out_dir": str(out),
        "piece_dir": str(out),
        "models": {"faster-whisper-small-verify": str(model_dir / "faster-whisper-small")},
        "assets": [str(wav_path)],
    }
    req_path = tmp_path / "vreq.json"
    res_path = tmp_path / "vres.json"
    req_path.write_text(json.dumps(request), encoding="utf-8")
    calls = tmp_path / "vcalls.jsonl"
    calls.touch()
    env = {
        **os.environ,
        "PYTHONPATH": str(stub_dir),
        "STUB_CALLS": str(calls),
        "STUB_HEARD": json.dumps([TEXT]),
    }
    done = subprocess.run(
        [
            sys.executable,
            str(PACKAGE / "runner.py"),
            "verify",
            "--input",
            str(req_path),
            "--result",
            str(res_path),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    verdict = _result(res_path)["assets"][0]
    assert verdict["passed"] is False
    assert verdict["metrics"]["digital_silence_run_ms"] > DROPOUT_MAX_MS


def test_run_cache_bypass(tmp_path: Path) -> None:
    facet_home = tmp_path / "home"
    key = _vs_cache_key("voxcpm2", "narradora", TEXT, "es", None, None, SEED)
    cache_wav = facet_home / "data" / "voicestudio" / "clip-cache" / f"{key}.wav"
    _write_tone_wav(cache_wav, int(RATE_HZ * 2.5))
    done, files = _run_vs(
        tmp_path,
        ["ready"],
        [TEXT],
        facet_home=facet_home,
        spec=_RunVS(extra_inputs={"cache": False}),
    )
    assert done.returncode == 0, done.stdout + done.stderr
    result = _result(tmp_path / "run-result.json")
    asset = result["assets"][0]
    assert asset["properties"]["cached"] is False
    bodies = _read_lines(files["bod"])
    assert len(bodies) >= 1


def test_run_failed_final_cached_hit_keeps_wav(tmp_path: Path) -> None:
    facet_home = tmp_path / "home"
    final_seed = SEED + MAX_TRIES - 1
    key = _vs_cache_key("voxcpm2", "narradora", TEXT, "es", None, None, final_seed)
    cache_wav = facet_home / "data" / "voicestudio" / "clip-cache" / f"{key}.wav"
    _write_dropout_wav(cache_wav, int(RATE_HZ * 2.5))
    heard = [BAD_HEARD] * (MAX_TRIES - 1) + [TEXT]
    done, files = _run_vs(tmp_path, ["ready"], heard, facet_home=facet_home)
    assert done.returncode == 0, done.stdout + done.stderr
    result = _result(tmp_path / "run-result.json")
    asset = result["assets"][0]
    assert asset["file"] == "intro.wav"
    assert asset["seed"] == final_seed
    assert asset["properties"]["cached"] is False
    assert (tmp_path / "out" / "intro.wav").is_file()
    assert not cache_wav.exists()
    bodies = _read_lines(files["bod"])
    assert len(bodies) == MAX_TRIES - 1
    assert "after 3 attempts" in done.stdout
    assert "keeping seed" in done.stdout
