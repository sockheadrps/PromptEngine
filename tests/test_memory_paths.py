from __future__ import annotations

from types import SimpleNamespace

from prompt_constructor import memory_routes


def _request(workspace: str = "workspace-123") -> SimpleNamespace:
    return SimpleNamespace(headers={"X-Workspace": workspace}, cookies={})


def _registry(title: str = "Wizard Tech Prank Caller", memory_config: dict | None = None) -> dict:
    return {
        "registry": {
            "version": 2,
            "title": title,
            "assembly_order": [],
            "memory_config": memory_config or {},
        }
    }


def test_memory_paths_scope_by_workspace_and_registry(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(memory_routes.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(memory_routes, "MULTI_TENANT", False)

    req = _request("user-one")
    cfg = {"store_path": "custom.db"}
    registry = _registry(memory_config={"personality_file": "personality.json"})

    store_path = memory_routes._resolve_store_path(req, "Wizard Tech Prank Caller", cfg)
    personality_path = memory_routes._resolve_personality_path(req, registry)

    expected_dir = tmp_path / ".promptlibretto" / "memory_stores" / "user-one" / "Wizard_Tech_Prank_Caller"
    assert store_path == str(expected_dir / "custom.db")
    assert personality_path == str(expected_dir / "personality.json")


def test_multi_tenant_ignores_custom_storage_paths(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(memory_routes.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(memory_routes, "MULTI_TENANT", True)

    req = _request("user-two")
    registry = _registry(
        "Same Title",
        memory_config={"personality_file": "/tmp/shared/personality.json"},
    )

    store_path = memory_routes._resolve_store_path(
        req,
        "Same Title",
        {"store_path": "/tmp/shared/memory.db"},
    )
    personality_path = memory_routes._resolve_personality_path(req, registry)

    expected_dir = tmp_path / ".promptlibretto" / "memory_stores" / "user-two" / "Same_Title"
    assert store_path == str(expected_dir / "memory.db")
    assert personality_path == str(expected_dir / "personality.json")
