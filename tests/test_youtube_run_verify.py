"""YouTube run, verify, preview, doctor and auth with the network replaced."""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import sys
import types
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "youtube"
SECRETS = ("CLIENT_ID", "CLIENT_SECRET", "REFRESH_TOKEN")


def _stub_sdk() -> types.ModuleType:
    stub = types.ModuleType("facet_runner_sdk")

    class Request:
        def __init__(self, data: dict[str, Any]) -> None:
            self.verb = str(data.get("verb", ""))
            self.capability = str(data.get("capability", ""))
            self.depth = str(data.get("depth", "quick"))
            self.inputs = dict(data.get("inputs") or {})
            self.out_dir = Path(str(data.get("out_dir", "")))
            self.piece_dir = Path(str(data.get("piece_dir", "")))
            self.assets = [Path(str(item)) for item in data.get("assets") or []]
            self.sources = [item for item in data.get("sources") or []]
            self.post = dict(data.get("post") or {})

        @classmethod
        def from_file(cls, path: Path) -> Request:
            return cls(json.loads(path.read_text()))

    class Runner:
        def __init__(self) -> None:
            self._verbs: dict[str, Any] = {}

        def verb(self, name: str):  # type: ignore[no-untyped-def]
            def register(function):  # type: ignore[no-untyped-def]
                self._verbs[name] = function
                return function

            return register

        def main(self) -> None:
            raise SystemExit(0)

    def secret(name: str) -> str:
        variable = f"FACET_SECRET_{name.upper().replace('-', '_')}"
        try:
            return os.environ[variable]
        except KeyError:
            raise KeyError(f"secret {name} is not set; run facet secret set") from None

    stub.Request = Request  # type: ignore[attr-defined]
    stub.Runner = Runner  # type: ignore[attr-defined]
    stub.secret = secret  # type: ignore[attr-defined]
    return stub


STUB = _stub_sdk()


def _load_runner() -> Any:
    sys.modules["facet_runner_sdk"] = STUB
    for name in ("youtube_runner", "video_meta", "youtube_client"):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location("youtube_runner", PACKAGE / "runner.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["youtube_runner"] = module
    with contextlib.suppress(SystemExit):
        spec.loader.exec_module(module)
    return module


RUNNER = _load_runner()
YouTubeError = RUNNER.YouTubeError
ChannelInfo = RUNNER.youtube_client.ChannelInfo


class FakeYouTube:
    def __init__(self) -> None:
        self.channel_info = ChannelInfo(id="UC123", title="Laboratorio", handle="@lab")
        self.upload_calls: list[dict[str, Any]] = []
        self.thumbnail_calls: list[dict[str, Any]] = []
        self.video_states: dict[str, dict[str, Any]] = {}
        self.counter = 0
        self.thumbnail_error: Exception | None = None
        self.channel_error: Exception | None = None

    def channel(self, client_id: str, client_secret: str, refresh_token: str) -> Any:
        if self.channel_error:
            raise self.channel_error
        return self.channel_info

    def upload_video(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        path: Any,
        body: dict[str, Any],
        notify_subscribers: bool,
        on_progress: Any = None,
    ) -> str:
        self.upload_calls.append(
            {
                "path": str(path),
                "body": body,
                "notify": notify_subscribers,
                "creds": (client_id, client_secret, refresh_token),
            }
        )
        self.counter += 1
        vid = f"vid{self.counter}"
        self.video_states.setdefault(
            vid,
            {
                "status": {
                    "privacyStatus": body["status"]["privacyStatus"],
                    "uploadStatus": "uploaded",
                },
                "processingDetails": {"processingStatus": "succeeded"},
            },
        )
        return vid

    def set_thumbnail(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        video_id: str,
        path: Any,
    ) -> None:
        self.thumbnail_calls.append({"video_id": video_id, "path": str(path)})
        if self.thumbnail_error:
            raise self.thumbnail_error

    def video_state(
        self, client_id: str, client_secret: str, refresh_token: str, video_id: str
    ) -> dict[str, Any]:
        if video_id not in self.video_states:
            raise YouTubeError("video not found")
        return self.video_states[video_id]


@pytest.fixture()
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeYouTube:
    net = FakeYouTube()
    for name in SECRETS:
        monkeypatch.setenv(f"FACET_SECRET_{name}", "s3cr3t")
    monkeypatch.setattr(RUNNER.youtube_client, "channel", net.channel)
    monkeypatch.setattr(RUNNER.youtube_client, "upload_video", net.upload_video)
    monkeypatch.setattr(RUNNER.youtube_client, "set_thumbnail", net.set_thumbnail)
    monkeypatch.setattr(RUNNER.youtube_client, "video_state", net.video_state)
    monkeypatch.setattr(RUNNER.video_meta, "probe", lambda path: None)
    return net


@pytest.fixture()
def files(tmp_path: Path) -> dict[str, Path]:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 64)
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"\xff\xd8\xff" + b"\x00" * 16)
    return {"video": video, "thumb": thumb, "dir": tmp_path}


def _inputs(files: dict[str, Path], **over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "video": str(files["video"]),
        "title": "La escuadra",
        "description": "Recién salida del banco.",
        "tags": ["taller"],
        "category": "28",
        "privacy": "private",
        "made-for-kids": False,
        "notify-subscribers": False,
    }
    data.update(over)
    return data


def _req(verb: str, files: dict[str, Path], data: dict[str, Any] | None = None) -> Any:
    payload = {
        "verb": verb,
        "capability": "youtube.upload",
        "inputs": _inputs(files),
        "out_dir": str(files["dir"]),
        "piece_dir": str(files["dir"]),
    }
    if data:
        payload.update(data)
    return STUB.Request(payload)


def test_run_uploads_with_body_and_notify_and_receipt(
    files: dict[str, Path], fake: FakeYouTube
) -> None:
    result = RUNNER.runner._verbs["run"](_req("run", files))
    assert result["tool"] == {"name": "YouTube", "version": "0.1.2"}
    post = result["post"]
    assert post["network"] == "youtube"
    assert post["account"] in {"@lab", "Laboratorio"}
    assert post["state"] == "private"
    assert post["posts"] == [{"id": "vid1", "url": "https://www.youtube.com/watch?v=vid1"}]
    assert post["cost"] is None
    assert len(fake.upload_calls) == 1
    call = fake.upload_calls[0]
    assert call["notify"] is False
    body = call["body"]
    assert body["snippet"] == {
        "title": "La escuadra",
        "description": "Recién salida del banco.",
        "tags": ["taller"],
        "categoryId": "28",
    }
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["selfDeclaredMadeForKids"] is False
    assert body["status"]["containsSyntheticMedia"] is False


@pytest.mark.parametrize("privacy", ["unlisted", "public"])
def test_run_and_verify_published_for_unlisted_or_public(
    privacy: str, files: dict[str, Path], fake: FakeYouTube
) -> None:
    req = _req("run", files, {"inputs": _inputs(files, privacy=privacy)})
    run_res = RUNNER.runner._verbs["run"](req)
    assert run_res["post"]["state"] == "published"
    assert fake.upload_calls[-1]["body"]["status"]["privacyStatus"] == privacy
    v_req = _req(
        "verify",
        files,
        {"post": run_res["post"], "sources": [{"path": str(files["video"])}]},
    )
    v_res = RUNNER.runner._verbs["verify"](v_req)
    assert v_res["state"] == "published"


def test_run_sets_synthetic_from_provenance(files: dict[str, Path], fake: FakeYouTube) -> None:
    req = _req("run", files, {"sources": [{"generated": True}]})
    RUNNER.runner._verbs["run"](req)
    assert fake.upload_calls[-1]["body"]["status"]["containsSyntheticMedia"] is True


def test_run_refuses_missing_made_for_kids(files: dict[str, Path], fake: FakeYouTube) -> None:
    inputs = _inputs(files)
    inputs.pop("made-for-kids")
    with pytest.raises(ValueError, match="made-for-kids"):
        RUNNER.runner._verbs["run"](_req("run", files, {"inputs": inputs}))


def test_run_thumbnail_failure_keeps_receipt_and_warns(
    files: dict[str, Path], fake: FakeYouTube
) -> None:
    fake.thumbnail_error = YouTubeError("channel not verified")
    req = _req("run", files, {"inputs": _inputs(files, thumbnail=str(files["thumb"]))})
    result = RUNNER.runner._verbs["run"](req)
    post = result["post"]
    assert post["posts"][0]["id"] == "vid1"
    assert post["state"] == "private"
    assert any(
        "thumbnail" in w.lower() or "warning" in w.lower() or "failed" in w.lower()
        for w in post.get("warnings", [])
    ) or post.get("warnings")
    assert fake.thumbnail_calls


def test_verify_ok(files: dict[str, Path], fake: FakeYouTube) -> None:
    run_res = RUNNER.runner._verbs["run"](_req("run", files))
    req = _req(
        "verify",
        files,
        {"post": run_res["post"], "sources": [{"path": str(files["video"])}]},
    )
    result = RUNNER.runner._verbs["verify"](req)
    assert result["state"] == "private"
    assert len(result["media"]) == 1


def test_verify_mismatch_privacy(files: dict[str, Path], fake: FakeYouTube) -> None:
    run_res = RUNNER.runner._verbs["run"](_req("run", files))
    fake.video_states["vid1"]["status"]["privacyStatus"] = "public"
    req = _req(
        "verify", files, {"post": run_res["post"], "sources": [{"path": str(files["video"])}]}
    )
    with pytest.raises(ValueError, match="privacy"):
        RUNNER.runner._verbs["verify"](req)


def test_verify_failed_upload_status(files: dict[str, Path], fake: FakeYouTube) -> None:
    run_res = RUNNER.runner._verbs["run"](_req("run", files))
    fake.video_states["vid1"]["status"]["uploadStatus"] = "failed"
    req = _req(
        "verify", files, {"post": run_res["post"], "sources": [{"path": str(files["video"])}]}
    )
    with pytest.raises(ValueError):
        RUNNER.runner._verbs["verify"](req)


def test_verify_processing_terminated(files: dict[str, Path], fake: FakeYouTube) -> None:
    run_res = RUNNER.runner._verbs["run"](_req("run", files))
    fake.video_states["vid1"]["processingDetails"]["processingStatus"] = "terminated"
    req = _req(
        "verify", files, {"post": run_res["post"], "sources": [{"path": str(files["video"])}]}
    )
    with pytest.raises(ValueError):
        RUNNER.runner._verbs["verify"](req)


def test_verify_absent_video(files: dict[str, Path], fake: FakeYouTube) -> None:
    req = _req(
        "verify",
        files,
        {
            "post": {
                "network": "youtube",
                "state": "private",
                "posts": [{"id": "missing", "url": "https://www.youtube.com/watch?v=missing"}],
            },
            "sources": [{"path": str(files["video"])}],
        },
    )
    with pytest.raises(ValueError):
        RUNNER.runner._verbs["verify"](req)


def test_preview_writes_post_schema(files: dict[str, Path], fake: FakeYouTube) -> None:
    receipt = files["dir"] / "clip.post.json"
    receipt.write_text(
        json.dumps(
            {
                "network": "youtube",
                "account": "@lab",
                "state": "private",
                "posts": [{"id": "vid1", "url": "https://www.youtube.com/watch?v=vid1"}],
            }
        )
    )
    req = _req("preview", files, {"assets": [str(receipt)]})
    result = RUNNER.runner._verbs["preview"](req)
    preview = json.loads((files["dir"] / "clip.post.json.preview.json").read_text())
    assert result == {"assets": [{"file": "clip.post.json.preview.json"}]}
    assert preview["preview"] == 1
    assert preview["kind"] == "post"
    assert preview["network"] == "youtube"
    assert preview["account"] == "@lab"
    assert preview["state"] == "private"
    assert preview["posts"][0]["text"] == "La escuadra\n\nRecién salida del banco."
    assert preview["posts"][0]["url"] == "https://www.youtube.com/watch?v=vid1"
    assert "clip.mp4" in preview["images"]


def test_doctor_full_reports_channel(files: dict[str, Path], fake: FakeYouTube) -> None:
    req = _req("doctor", files, {"depth": "full"})
    checks = {c["name"]: c for c in RUNNER.runner._verbs["doctor"](req)["checks"]}
    assert checks["session"]["ok"] is True
    assert "Laboratorio" in checks["session"]["detail"]
    assert "@lab" in checks["session"]["detail"]


def test_doctor_quick_names_missing_secret(
    files: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("CLIENT_ID", "CLIENT_SECRET"):
        monkeypatch.setenv(f"FACET_SECRET_{name}", "s3cr3t")
    req = _req("doctor", files, {"depth": "quick"})
    checks = {c["name"]: c for c in RUNNER.runner._verbs["doctor"](req)["checks"]}
    assert checks["refresh-token"]["ok"] is False
    assert (
        "facet auth youtube" in checks["refresh-token"]["fix"]
        or "facet" in checks["refresh-token"]["fix"]
    )


def test_auth_returns_secrets(files: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FACET_SECRET_CLIENT_ID", "cid")
    monkeypatch.setenv("FACET_SECRET_CLIENT_SECRET", "csecret")

    def _authorize(cid: str, csecret: str) -> dict[str, str]:
        return {"client-id": cid, "client-secret": csecret, "refresh-token": "rtok"}

    monkeypatch.setattr(RUNNER.youtube_client, "authorize", _authorize)
    req = _req("auth", files)
    result = RUNNER.runner._verbs["auth"](req)
    assert result == {
        "secrets": {"client-id": "cid", "client-secret": "csecret", "refresh-token": "rtok"}
    }


def test_auth_refuses_no_refresh(files: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FACET_SECRET_CLIENT_ID", "cid")
    monkeypatch.setenv("FACET_SECRET_CLIENT_SECRET", "csecret")

    def _authorize(cid: str, csecret: str) -> dict[str, str]:
        raise YouTubeError("no refresh token was returned")

    monkeypatch.setattr(RUNNER.youtube_client, "authorize", _authorize)
    with pytest.raises(ValueError, match="refresh"):
        RUNNER.runner._verbs["auth"](_req("auth", files))


def test_auth_requires_client_id_secret(
    files: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FACET_SECRET_CLIENT_ID", raising=False)
    monkeypatch.setenv("FACET_SECRET_CLIENT_SECRET", "csecret")
    with pytest.raises((ValueError, KeyError)):
        RUNNER.runner._verbs["auth"](_req("auth", files))
