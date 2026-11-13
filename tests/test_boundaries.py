from pathlib import Path

from babysitter.platform import hidden_creation_flags, popen_hidden
from babysitter.version import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_source_never_invokes_a_shell():
    root = ROOT / "src"
    banned = ("shell=True", "shell = True", "os.system(", "os.popen(")
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for snippet in banned:
            assert snippet not in text, f"{path} contains {snippet}"


def test_http_targets_are_local_or_documented_pages():
    allowed_prefixes = (
        "http://127.0.0.1",
        "https://ollama.com",
        "https://github.com/ollama/ollama",
        # Optional social search. Off unless the user turns it on.
        "https://api.scrapecreators.com",
        "https://github.com/ScrapeCreators/social-media-research-skills",
        # Built only after the host is checked to be 127.0.0.1.
        "http://{self.host}:{self.port}",
    )
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in ("http://", "https://"):
            start = 0
            while True:
                index = text.find(token, start)
                if index == -1:
                    break
                end = index
                while end < len(text) and text[end] not in " \n\"')":
                    end += 1
                url = text[index:end]
                assert url.startswith(allowed_prefixes), url
                start = end


def test_hidden_launch_never_sets_shell(monkeypatch):
    captured = {}

    class FakeProcess:
        pid = 1

        def poll(self):
            return None

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr("babysitter.platform.subprocess.Popen", fake_popen)
    popen_hidden(["ollama", "serve"], stdout=None)
    assert captured["kwargs"]["shell"] is False
    assert captured["args"] == ["ollama", "serve"]


def test_windows_creation_flag(monkeypatch):
    monkeypatch.setattr("babysitter.platform.sys.platform", "win32")
    assert hidden_creation_flags() == 0x08000000


def test_installer_version_matches_the_one_version_file():
    text = (ROOT / "installer" / "BabySitter.iss").read_text(encoding="utf-8")
    assert f'#define MyAppVersion "{__version__}"' in text
