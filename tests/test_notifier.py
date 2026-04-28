from __future__ import annotations

from types import SimpleNamespace

from cc_buddy_bridge import notifier


def test_notify_turn_complete_windows_uses_winsound(monkeypatch):
    calls: list[int] = []

    monkeypatch.setattr(notifier.platform, "system", lambda: "Windows")
    monkeypatch.setitem(
        __import__("sys").modules,
        "winsound",
        SimpleNamespace(
            MB_ICONASTERISK=64,
            MessageBeep=lambda kind: calls.append(kind),
        ),
    )

    notifier.notify_turn_complete(session_id="ses-1")

    assert calls == [64]


def test_notify_turn_complete_macos_spawns_banner_and_sound(monkeypatch):
    calls: list[list[str]] = []

    monkeypatch.setattr(notifier.platform, "system", lambda: "Darwin")

    def fake_popen(args, stdout=None, stderr=None):
        calls.append(args)
        return SimpleNamespace()

    monkeypatch.setattr(notifier.subprocess, "Popen", fake_popen)

    notifier.notify_turn_complete(subtitle="done", session_id="ses-2")

    assert calls[0][0] == "osascript"
    assert calls[1] == ["afplay", notifier.SOUND_FILE]
