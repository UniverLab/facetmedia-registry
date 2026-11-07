"""The voicestudio profile capability: a local clone from the person's samples.

Everything runs against a stub backend in a thread and a stub ``pyloudnorm``
that reports RMS as loudness, so no GPU, no model and no real voice take is
needed. The stub backend enforces the real one's two save-time rules: a 400
for an empty name and a 422 for a clone save with no ``ref_audio`` part.

The tests assert the observable contract: the 7-30 s guard, the single-empty-
channel repair, the -20 LUFS normalisation, the multipart fields the backend
requires, the receipt with the returned id, verify against the profile
listing, and the generic preview file. Locality is checked by proving no
audio file ever lands beside the piece or in the package directory.
"""

from __future__ import annotations

import importlib.util
import io
import json
import math
import threading
import tomllib
import wave
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy
import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "voicestudio"
GENERIC_SCHEMA: dict[str, Any] = json.loads(
    (ROOT / "schemas" / "preview" / "generic.schema.json").read_text(encoding="utf-8")
)

#: The profile the stub backend creates and lists.
PROFILE_ID = "d4e9ee57"
#: The lab's accepted reference window and loudness target.
MIN_S = 7.0
MAX_S = 30.0
TARGET_LUFS = -20.0
#: A sample rate and amplitude that reach -20 LUFS without hitting the peak cap.
RATE_HZ = 16_000
AMPLITUDE = 0.1
#: What the stub backend's GET /profiles answers.
PROFILES = [{"id": PROFILE_ID, "name": "jheison", "kind": "clone", "language": "es"}]
#: One valid take: inside the window, below the peak cap before normalising.
VALID_SECONDS = 9.0
#: The sample width of a 16-bit PCM WAV, in bytes.
PCM16_WIDTH = 2

#: The pull-time SDK surface the runner touches; ``main`` stands down in-process.
STUB_SDK = """
import json
import os
import sys
from pathlib import Path


class Request:
    def __init__(self, data):
        self.verb = str(data.get("verb", ""))
        self.capability = str(data.get("capability", ""))
        self.depth = str(data.get("depth", "quick"))
        self.inputs = dict(data.get("inputs") or {})
        self.out_dir = Path(str(data.get("out_dir", "")))
        self.piece_dir = Path(str(data.get("piece_dir", "")))
        self.assets = [Path(str(item)) for item in data.get("assets") or []]
        self._models = {str(k): Path(str(v)) for k, v in (data.get("models") or {}).items()}

    @classmethod
    def from_file(cls, path):
        return cls(json.loads(Path(path).read_text()))

    def model_path(self, model_id):
        return self._models[model_id]


class Runner:
    def __init__(self):
        self._verbs = {}

    def verb(self, name):
        def register(function):
            self._verbs[name] = function
            return function

        return register

    def main(self):
        if os.environ.get("STUB_SDK_NO_MAIN"):
            return 0
        raise SystemExit(0)
"""

#: The loudness meter the registry environment has no distribution for.
STUB_LOUDNESS = """
import math

import numpy


class Meter:
    def __init__(self, rate):
        self.rate = rate

    def integrated_loudness(self, samples):
        data = numpy.asarray(samples, dtype=float)
        if data.ndim > 1:
            data = data.mean(axis=1)
        if not data.size:
            return -math.inf
        rms = float(numpy.sqrt(numpy.mean(numpy.square(data))))
        if rms <= 0.0:
            return -math.inf
        return 20.0 * math.log10(rms)
"""


def _stub_dir(tmp_path: Path) -> Path:
    """The PYTHONPATH stub: the SDK, the loudness meter, and textnorm's home."""
    folder = tmp_path / "stub"
    folder.mkdir(exist_ok=True)
    (folder / "facet_runner_sdk.py").write_text(STUB_SDK, encoding="utf-8")
    (folder / "pyloudnorm.py").write_text(STUB_LOUDNESS, encoding="utf-8")
    facet_lib = folder / "facet_lib"
    facet_lib.mkdir(exist_ok=True)
    (facet_lib / "__init__.py").write_text("", encoding="utf-8")
    (facet_lib / "textnorm.py").write_text(
        (ROOT / "lib" / "textnorm.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    return folder


def _import_runner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """The runner in-process: the profile verbs need no SDK main and no whisper."""
    stub_dir = _stub_dir(tmp_path)
    monkeypatch.setenv("STUB_SDK_NO_MAIN", "1")
    monkeypatch.syspath_prepend(str(stub_dir))
    spec = importlib.util.spec_from_file_location(
        "voicestudio_runner_profile", PACKAGE / "runner.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_wav(
    path: Path,
    seconds: float,
    *,
    amplitude: float = AMPLITUDE,
    channels: int = 1,
    silent: tuple[int, ...] = (),
    rate: int = RATE_HZ,
) -> Path:
    """A sine reference on disk, with the named channels left at digital zero."""
    count = int(seconds * rate)
    tone = amplitude * numpy.sin(2.0 * numpy.pi * 220.0 * numpy.arange(count) / rate)
    if channels > 1:
        data = numpy.stack([tone] * channels, axis=1)
        for channel in silent:
            data[:, channel] = 0.0
    else:
        data = tone
    pcm = numpy.clip(numpy.round(data * 32767.0), -32768.0, 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(pcm.tobytes())
    return path


def _wav_seconds(source: Path | io.BytesIO) -> float:
    with wave.open(str(source) if isinstance(source, Path) else source, "rb") as reader:
        return reader.getnframes() / reader.getframerate()


def _decode_mono(data: bytes) -> tuple[numpy.ndarray, int]:
    """The returned WAV as floats; fails unless it is 16-bit mono PCM."""
    with wave.open(io.BytesIO(data), "rb") as reader:
        assert reader.getnchannels() == 1
        assert reader.getsampwidth() == PCM16_WIDTH
        rate = reader.getframerate()
        pcm = reader.readframes(reader.getnframes())
    return numpy.frombuffer(pcm, dtype="<i2").astype(numpy.float64) / 32768.0, rate


def _loudness(samples: numpy.ndarray) -> float:
    """The same RMS meter the stub pyloudnorm serves."""
    rms = float(numpy.sqrt(numpy.mean(numpy.square(samples))))
    return 20.0 * float(numpy.log10(rms)) if rms > 0 else -math.inf


def _multipart(body: bytes, content_type: str) -> tuple[dict[str, str], dict[str, bytes]]:
    """The form fields and file parts of one multipart body."""
    message = BytesParser(policy=email_policy).parsebytes(
        b"Content-Type: " + content_type.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
    )
    fields: dict[str, str] = {}
    files: dict[str, bytes] = {}
    for part in message.iter_parts():
        name = str(part.get_param("name", header="content-disposition"))
        payload = part.get_payload(decode=True) or b""
        if part.get_filename() is None:
            fields[name] = payload.decode("utf-8")
        else:
            files[name] = payload
    return fields, files


class _Backend:
    """A stub VoiceStudio that enforces the real save-time rules and records posts."""

    def __init__(
        self,
        profiles: Any = None,
        *,
        fail_code: int = 0,
        profile_id: str = PROFILE_ID,
    ) -> None:
        self.profiles = PROFILES if profiles is None else profiles
        self.fail_code = fail_code
        self.profile_id = profile_id
        self.posts: list[dict[str, Any]] = []
        self.gets: list[str] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def send(self, handler: BaseHTTPRequestHandler, code: int, payload: Any) -> None:
        body = json.dumps(payload).encode()
        handler.send_response(code)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def answer_post(self, handler: BaseHTTPRequestHandler) -> None:
        length = int(handler.headers.get("Content-Length", "0"))
        body = handler.rfile.read(length)
        if self.fail_code:
            self.send(handler, self.fail_code, {"detail": "the backend refused the save"})
            return
        fields, files = _multipart(body, handler.headers.get("Content-Type", ""))
        if not fields.get("name", "").strip():
            self.send(handler, 400, {"detail": "A voice profile needs a name."})
            return
        if fields.get("kind", "clone") == "clone" and "ref_audio" not in files:
            self.send(handler, 422, {"detail": "clone profiles require ref_audio"})
            return
        self.posts.append({"fields": fields, "files": files})
        record = {
            "id": self.profile_id,
            "name": fields["name"],
            "kind": fields.get("kind", "clone"),
            "language": fields.get("language", "es"),
        }
        self.send(handler, 200, record)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        backend = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: object) -> None:
                return None

            def do_GET(self) -> None:
                backend.gets.append(self.path)
                if self.path == "/profiles":
                    backend.send(self, 200, backend.profiles)
                elif self.path == "/model/status":
                    backend.send(self, 200, {"status": "ready"})
                else:
                    self.send_error(404)

            def do_POST(self) -> None:
                if self.path != "/profiles":
                    self.send_error(404)
                    return
                backend.answer_post(self)

        return Handler


@pytest.fixture
def backend() -> Any:
    server = _Backend()
    try:
        yield server
    finally:
        server.close()


def _request(
    capability: str, inputs: dict[str, Any], out_dir: Path, assets: list[Path] | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        capability=capability,
        inputs=inputs,
        out_dir=out_dir,
        piece_dir=out_dir,
        assets=assets or [],
    )


def _profile_inputs(ref: Path, name: str = "jheison") -> dict[str, Any]:
    return {
        "name": name,
        "ref-audio": str(ref),
        "instruct": "female, low pitch",
        "language": "es",
    }


def _run_profile(module: Any, backend: _Backend, tmp_path: Path, seconds: float = VALID_SECONDS):
    take = _write_wav(tmp_path / "take.wav", seconds)
    out = tmp_path / "out"
    out.mkdir()
    request = _request(module.PROFILE_CAPABILITY, _profile_inputs(take), out)
    return module.run(request), out, take


def test_a_reference_shorter_than_seven_seconds_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _import_runner(monkeypatch, tmp_path)
    take = _write_wav(tmp_path / "short.wav", MIN_S - 0.2)
    with pytest.raises(ValueError, match=r"6\.8 s.*7-30 s") as caught:
        module._profile_module().validate_ref(take)
    assert "neutral speech" in str(caught.value)


def test_a_reference_longer_than_thirty_seconds_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _import_runner(monkeypatch, tmp_path)
    take = _write_wav(tmp_path / "long.wav", MAX_S + 0.2)
    with pytest.raises(ValueError, match=r"30\.2 s.*7-30 s"):
        module._profile_module().validate_ref(take)


def test_a_stereo_take_with_one_silent_channel_keeps_the_live_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The laptop case: voice on the right, digital silence on the left."""
    module = _import_runner(monkeypatch, tmp_path)
    take = _write_wav(tmp_path / "stereo.wav", VALID_SECONDS, channels=2, silent=(0,))
    audio, repairs = module._profile_module().validate_ref(take)
    assert repairs == ["kept the right channel; the other channel is silent"]
    samples, _rate = _decode_mono(audio)
    assert float(numpy.max(numpy.abs(samples))) > 0.0


def test_the_reference_is_normalised_to_minus_twenty_lufs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _import_runner(monkeypatch, tmp_path)
    take = _write_wav(tmp_path / "quiet.wav", VALID_SECONDS)
    audio, repairs = module._profile_module().validate_ref(take)
    assert repairs == []
    samples, _rate = _decode_mono(audio)
    assert _loudness(samples) == pytest.approx(TARGET_LUFS, abs=0.3)
    assert _wav_seconds(io.BytesIO(audio)) == pytest.approx(VALID_SECONDS, abs=0.01)


def test_the_run_writes_the_receipt_with_the_returned_profile_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, backend: _Backend
) -> None:
    monkeypatch.setenv("FACET_SERVER_URL", backend.url)
    module = _import_runner(monkeypatch, tmp_path)
    result, out, _take = _run_profile(module, backend, tmp_path)
    assert backend.posts, "the profile was never posted"
    assets = result["assets"]
    assert len(assets) == 1
    asset = assets[0]
    assert asset["file"] == "jheison.profile.json"
    assert asset["kind"] == "text"
    assert asset["mime"] == "application/json"
    assert asset["properties"]["profile_id"] == PROFILE_ID
    assert asset["params"]["name"] == "jheison"
    assert asset["params"]["language"] == "es"
    receipt = json.loads((out / "jheison.profile.json").read_text(encoding="utf-8"))
    assert receipt == {"id": PROFILE_ID, "name": "jheison", "language": "es"}


def test_the_post_carries_the_backend_contract_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, backend: _Backend
) -> None:
    """kind=clone, language, ref_text="" and the ref_audio file part, once."""
    monkeypatch.setenv("FACET_SERVER_URL", backend.url)
    module = _import_runner(monkeypatch, tmp_path)
    _run_profile(module, backend, tmp_path)
    assert len(backend.posts) == 1
    fields = backend.posts[0]["fields"]
    assert fields["name"] == "jheison"
    assert fields["kind"] == "clone"
    assert fields["language"] == "es"
    assert fields["ref_text"] == ""
    assert fields["instruct"] == "female, low pitch"
    audio = backend.posts[0]["files"]["ref_audio"]
    assert audio.startswith(b"RIFF")
    assert _wav_seconds(io.BytesIO(audio)) == pytest.approx(VALID_SECONDS, abs=0.05)


def test_a_relative_ref_audio_resolves_against_the_piece_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, backend: _Backend
) -> None:
    """``ref-audio = "samples/x.wav"`` is relative to the piece file, not the CWD."""
    monkeypatch.setenv("FACET_SERVER_URL", backend.url)
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path / "elsewhere")
    module = _import_runner(monkeypatch, tmp_path)
    take = _write_wav(tmp_path / "take.wav", VALID_SECONDS)
    out = tmp_path / "out"
    out.mkdir()
    inputs = _profile_inputs(take)
    inputs["ref-audio"] = "take.wav"
    request = _request(module.PROFILE_CAPABILITY, inputs, out)
    request.piece_dir = tmp_path
    result = module.run(request)
    assert result["assets"][0]["file"] == "jheison.profile.json"
    assert backend.posts


def test_an_empty_name_is_refused_before_any_post(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, backend: _Backend
) -> None:
    monkeypatch.setenv("FACET_SERVER_URL", backend.url)
    module = _import_runner(monkeypatch, tmp_path)
    take = _write_wav(tmp_path / "take.wav", VALID_SECONDS)
    out = tmp_path / "out"
    out.mkdir()
    request = _request(module.PROFILE_CAPABILITY, _profile_inputs(take, name=""), out)
    with pytest.raises(RuntimeError, match="needs a name"):
        module.run(request)
    assert backend.posts == []
    assert list(out.iterdir()) == []


@pytest.mark.parametrize("code", [422, 500])
def test_a_rejected_post_fails_naming_the_backend_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, code: int
) -> None:
    refused = _Backend(fail_code=code)
    try:
        monkeypatch.setenv("FACET_SERVER_URL", refused.url)
        module = _import_runner(monkeypatch, tmp_path)
        with pytest.raises(RuntimeError, match=str(code)) as caught:
            _run_profile(module, refused, tmp_path)
        assert "the backend refused the save" in str(caught.value)
        assert refused.posts == []
    finally:
        refused.close()


def test_verify_passes_a_receipt_whose_id_is_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, backend: _Backend
) -> None:
    """The verify verb reads the receipt and asks the profiles listing."""
    monkeypatch.setenv("FACET_SERVER_URL", backend.url)
    module = _import_runner(monkeypatch, tmp_path)
    receipt = tmp_path / "jheison.profile.json"
    receipt.write_text(
        json.dumps({"id": PROFILE_ID, "name": "jheison", "language": "es"}), encoding="utf-8"
    )

    def no_whisper(_req: Any) -> Any:
        raise AssertionError("a profile receipt must not load the transcriber")

    monkeypatch.setattr(module, "_whisper", no_whisper)
    result = module.verify(_request(module.PROFILE_CAPABILITY, {}, tmp_path, [receipt]))
    verdict = result["assets"][0]
    assert verdict["file"] == "jheison.profile.json"
    assert verdict["passed"] is True
    assert verdict["metrics"] == {"profile_id": PROFILE_ID, "profiles": 1}
    assert verdict["verifier"] == "voicestudio-profiles"
    assert backend.gets == ["/profiles"]


def test_verify_fails_a_receipt_the_backend_no_longer_lists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    other = _Backend(profiles=[{"id": "00000000", "name": "otra"}])
    try:
        monkeypatch.setenv("FACET_SERVER_URL", other.url)
        module = _import_runner(monkeypatch, tmp_path)
        receipt = tmp_path / "jheison.profile.json"
        receipt.write_text(json.dumps({"id": PROFILE_ID, "name": "jheison"}), encoding="utf-8")
        result = module.verify(_request(module.PROFILE_CAPABILITY, {}, tmp_path, [receipt]))
        assert result["assets"][0]["passed"] is False
    finally:
        other.close()


def test_an_unreadable_profile_listing_fails_the_verification(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    broken = _Backend(profiles={"not": "a list"})
    try:
        monkeypatch.setenv("FACET_SERVER_URL", broken.url)
        module = _import_runner(monkeypatch, tmp_path)
        receipt = tmp_path / "jheison.profile.json"
        receipt.write_text(json.dumps({"id": PROFILE_ID}), encoding="utf-8")
        with pytest.raises(RuntimeError, match="GET /profiles failed"):
            module.verify(_request(module.PROFILE_CAPABILITY, {}, tmp_path, [receipt]))
    finally:
        broken.close()


def test_preview_writes_the_generic_preview_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _import_runner(monkeypatch, tmp_path)
    receipt = tmp_path / "jheison.profile.json"
    receipt.write_text(
        json.dumps({"id": PROFILE_ID, "name": "jheison", "language": "es"}), encoding="utf-8"
    )
    result = module.preview(_request(module.PROFILE_CAPABILITY, {}, tmp_path, [receipt]))
    entry = result["assets"][0]
    preview_path = tmp_path / "jheison.profile.json.preview.json"
    assert entry == {
        "file": "jheison.profile.json",
        "preview": "jheison.profile.json.preview.json",
        "images": [],
    }
    data = json.loads(preview_path.read_text(encoding="utf-8"))
    assert data["preview"] == 1
    assert data["kind"] == "text"
    assert data["fields"] == {"id": PROFILE_ID, "name": "jheison", "language": "es"}
    assert set(data) == set(GENERIC_SCHEMA["required"])
    assert len(data["summary"]) <= GENERIC_SCHEMA["properties"]["summary"]["maxLength"]


def test_no_sample_bytes_land_beside_the_piece_or_in_the_package(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, backend: _Backend
) -> None:
    """The sample goes to the backend only: the run leaves one receipt."""
    monkeypatch.setenv("FACET_SERVER_URL", backend.url)
    module = _import_runner(monkeypatch, tmp_path)
    result, out, take = _run_profile(module, backend, tmp_path)
    assert sorted(path.name for path in out.iterdir()) == ["jheison.profile.json"]
    assert sorted(path.name for path in tmp_path.glob("*.wav")) == ["take.wav"]
    assert take.read_bytes().startswith(b"RIFF")
    assert backend.posts[0]["files"]["ref_audio"].startswith(b"RIFF")
    assert not list(PACKAGE.rglob("*.wav"))
    assert not list(PACKAGE.rglob("*.profile.json"))
    receipt = json.loads((out / "jheison.profile.json").read_text(encoding="utf-8"))
    assert set(receipt) == {"id", "name", "language"}
    assert result["assets"][0]["file"] == "jheison.profile.json"


def test_the_package_declares_the_profile_capability_as_text_with_the_generic_viewer() -> None:
    manifest = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
    profile = manifest["capabilities"]["profile"]
    assert profile["kind"] == "text"
    assert profile["preview"] == {"viewer": "generic"}
    assert profile["inputs"]["ref-audio"]["type"] == "path"
    assert profile["inputs"]["ref-audio"]["required"] is True
    assert profile["inputs"]["language"]["values"] == ["es"]
    assert profile["inputs"]["language"]["default"] == "es"
    assert profile["inputs"]["name"]["type"] == "string"
    assert profile["inputs"]["name"]["required"] is True
