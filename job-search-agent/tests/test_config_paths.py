import os

from jobagent import paths
from jobagent.config import load_config


def test_relative_runtime_paths_resolve_against_home(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBAGENT_HOME", str(tmp_path))
    import importlib
    import jobagent.paths as p
    importlib.reload(p)
    import jobagent.config as c
    importlib.reload(c)
    try:
        cfg = c.load_config(p.CONFIG_PATH)
        assert os.path.isabs(cfg.storage.sqlite_path)
        assert os.path.isabs(cfg.browser.user_data_dir)
        assert str(tmp_path).lower() in cfg.storage.sqlite_path.lower()
    finally:
        monkeypatch.undo()
        importlib.reload(p)
        importlib.reload(c)


def test_absolute_paths_untouched(cfg):
    assert os.path.isabs(cfg.storage.sqlite_path)
    assert os.path.isabs(cfg.browser.user_data_dir)