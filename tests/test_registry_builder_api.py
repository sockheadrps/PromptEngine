"""
tests/test_registry_builder_api.py

Unit tests for promptlibretto/registry/builder_api.py.
All tests are pure-Python — no MCP dependency required.
"""
import pytest
from promptlibretto.registry import builder_api as api


# ── helpers ───────────────────────────────────────────────────────────────────

def make_draft(**kwargs):
    result = api.draft_create(**kwargs)
    return result["draft_id"], result["registry"]


# ── draft lifecycle ───────────────────────────────────────────────────────────

class TestDraftLifecycle:
    def test_create_returns_draft_id_and_registry(self):
        did, reg = make_draft(title="T", description="D")
        assert isinstance(did, str) and len(did) == 8
        assert reg["title"] == "T"
        assert reg["version"] == 2

    def test_get_round_trips(self):
        did, _ = make_draft()
        got = api.draft_get(did)
        assert got["draft_id"] == did
        assert "registry" in got

    def test_get_unknown_raises(self):
        with pytest.raises(KeyError, match="not found"):
            api.draft_get("00000000")

    def test_reset_clears_items_keeps_title(self):
        did, _ = make_draft(title="Keep Me")
        api.meta_set(did, description="desc")
        api.section_add_item(did, "personas", "p1", {"context": "hello"})
        api.draft_reset(did)
        reg = api.draft_get(did)["registry"]
        assert reg["title"] == "Keep Me"
        assert reg["personas"]["items"] == []


# ── meta ──────────────────────────────────────────────────────────────────────

class TestMeta:
    def test_set_title_and_description(self):
        did, _ = make_draft()
        result = api.meta_set(did, title="Foo", description="Bar")
        assert result == {"title": "Foo", "description": "Bar"}

    def test_partial_update_preserves_other(self):
        did, _ = make_draft(title="Original")
        api.meta_set(did, description="New desc")
        reg = api.draft_get(did)["registry"]
        assert reg["title"] == "Original"
        assert reg["description"] == "New desc"


# ── section vars ──────────────────────────────────────────────────────────────

class TestSectionVars:
    def test_add_bare_var(self):
        did, _ = make_draft()
        result = api.section_add_var(did, "personas", "persona")
        assert "persona" in result["template_vars"]

    def test_add_braced_var_normalizes(self):
        did, _ = make_draft()
        result = api.section_add_var(did, "personas", "{persona}")
        assert "persona" in result["template_vars"]
        assert "{persona}" not in result["template_vars"]

    def test_duplicate_var_not_added_twice(self):
        did, _ = make_draft()
        api.section_add_var(did, "personas", "persona")
        api.section_add_var(did, "personas", "persona")
        tvars = api.draft_get(did)["registry"]["personas"]["template_vars"]
        assert tvars.count("persona") == 1

    def test_unknown_section_raises(self):
        did, _ = make_draft()
        with pytest.raises(ValueError, match="Unknown section"):
            api.section_add_var(did, "nonexistent", "var")


# ── section items ─────────────────────────────────────────────────────────────

class TestSectionItems:
    def test_add_persona_item(self):
        did, _ = make_draft()
        result = api.section_add_item(did, "personas", "wizard", {"context": "You are a wizard."})
        assert result["item"]["id"] == "wizard"
        assert result["item"]["context"] == "You are a wizard."

    def test_add_sentiment_item_with_scale(self):
        did, _ = make_draft()
        result = api.section_add_item(
            did, "sentiment", "calm",
            {"context": "Calm tone.", "scale": {"min": 0, "max": 1}},
        )
        assert result["item"]["scale"] == {"min": 0, "max": 1}

    def test_add_prompt_ending_uses_name(self):
        did, _ = make_draft()
        result = api.section_add_item(
            did, "prompt_endings", "any_id",
            {"name": "default_ending", "text": "Respond helpfully."},
        )
        item = result["item"]
        assert item.get("name") == "default_ending"
        assert "id" not in item

    def test_add_base_context_item(self):
        did, _ = make_draft()
        result = api.section_add_item(
            did, "base_context", "ctx1",
            {"text": "You are helpful.", "template_vars": ["{persona}"]},
        )
        assert result["item"]["template_vars"] == ["persona"]

    def test_duplicate_item_raises(self):
        did, _ = make_draft()
        api.section_add_item(did, "personas", "p1", {"context": "A"})
        with pytest.raises(ValueError, match="already exists"):
            api.section_add_item(did, "personas", "p1", {"context": "B"})


# ── item update ───────────────────────────────────────────────────────────────

class TestItemUpdate:
    def test_update_context(self):
        did, _ = make_draft()
        api.section_add_item(did, "personas", "p1", {"context": "Old"})
        result = api.item_update(did, "personas", "p1", {"context": "New"})
        assert result["item"]["context"] == "New"

    def test_update_protects_id(self):
        did, _ = make_draft()
        api.section_add_item(did, "personas", "p1", {"context": "A"})
        api.item_update(did, "personas", "p1", {"id": "evil", "context": "B"})
        item = api.draft_get(did)["registry"]["personas"]["items"][0]
        assert item["id"] == "p1"

    def test_update_missing_item_raises(self):
        did, _ = make_draft()
        with pytest.raises(KeyError):
            api.item_update(did, "personas", "ghost", {"context": "X"})


# ── fragments ─────────────────────────────────────────────────────────────────

class TestFragments:
    def test_add_fragment_no_condition(self):
        did, _ = make_draft()
        api.section_add_item(did, "personas", "p1", {"context": "Base"})
        result = api.item_add_fragment(did, "personas", "p1", "frag1", "Extra text.")
        assert result["fragment"]["text"] == "Extra text."
        assert "condition" not in result["fragment"]

    def test_add_fragment_with_condition_auto_adds_var(self):
        did, _ = make_draft()
        api.section_add_item(did, "personas", "p1", {"context": "Base"})
        api.item_add_fragment(did, "personas", "p1", "frag1", "More text.", condition="{persona}")
        reg = api.draft_get(did)["registry"]
        assert "persona" in reg["personas"]["template_vars"]
        frag = reg["personas"]["items"][0]["fragments"][0]
        assert frag["condition"] == "persona"

    def test_add_fragment_missing_item_raises(self):
        did, _ = make_draft()
        with pytest.raises(KeyError):
            api.item_add_fragment(did, "personas", "ghost", "f1", "text")


# ── groups ────────────────────────────────────────────────────────────────────

class TestGroups:
    def test_item_add_group_creates_inline(self):
        did, _ = make_draft()
        api.section_add_item(did, "personas", "p1", {"context": "Base"})
        result = api.item_add_group(
            did, "personas", "p1", "g1",
            directives=["Be concise.", "Use bullets."],
            pre_context="Follow these rules:",
        )
        assert result["created"] is True
        assert result["group"]["id"] == "g1"
        assert len(result["group"]["items"]) == 2

    def test_item_add_group_appends_directives(self):
        did, _ = make_draft()
        api.section_add_item(did, "personas", "p1", {"context": "Base"})
        api.item_add_group(did, "personas", "p1", "g1", directives=["First."])
        result = api.item_add_group(did, "personas", "p1", "g1", directives=["Second."])
        assert result["created"] is False
        assert len(result["group"]["items"]) == 2

    def test_group_add_item_finds_across_sections(self):
        did, _ = make_draft()
        api.section_add_item(did, "personas", "p1", {"context": "Base"})
        api.item_add_group(did, "personas", "p1", "g1", directives=["Initial."])
        result = api.group_add_item(did, "g1", "Added later.")
        assert "Added later." in result["items"]

    def test_group_add_item_unknown_group_raises(self):
        did, _ = make_draft()
        with pytest.raises(KeyError, match="not found"):
            api.group_add_item(did, "nope", "something")


# ── assembly ──────────────────────────────────────────────────────────────────

class TestAssembly:
    def test_set_order(self):
        did, _ = make_draft()
        order = ["base_context.text", "personas.context", "user_message.text"]
        result = api.assembly_set_order(did, order)
        assert result["assembly_order"] == order

    def test_set_order_overwrites(self):
        did, _ = make_draft()
        api.assembly_set_order(did, ["a.text"])
        api.assembly_set_order(did, ["b.text", "c.text"])
        assert api.draft_get(did)["registry"]["assembly_order"] == ["b.text", "c.text"]


# ── generation / output policy ────────────────────────────────────────────────

class TestGenerationAndPolicy:
    def test_generation_set_merges(self):
        did, _ = make_draft()
        api.generation_set(did, {"temperature": 0.7})
        result = api.generation_set(did, {"top_p": 0.9})
        assert result["generation"]["temperature"] == 0.7
        assert result["generation"]["top_p"] == 0.9

    def test_output_policy_set_merges(self):
        did, _ = make_draft()
        api.output_policy_set(did, {"strip_thinking": True})
        result = api.output_policy_set(did, {"format": "markdown"})
        assert result["output_policy"]["strip_thinking"] is True
        assert result["output_policy"]["format"] == "markdown"



# ── validation ────────────────────────────────────────────────────────────────

class TestValidation:
    def test_fresh_draft_fails_required_sections(self):
        did, _ = make_draft()
        result = api.draft_validate(did)
        assert result["ok"] is False
        paths = [e["path"] for e in result["errors"]]
        assert "personas.items" in paths
        assert "sentiment.items" in paths

    def test_fully_populated_draft_passes(self):
        did, _ = make_draft(title="Test", description="Desc")
        api.section_add_item(did, "base_context", "ctx", {"text": "You are helpful."})
        api.section_add_item(did, "personas", "main", {"context": "Helpful assistant."})
        api.section_add_item(did, "sentiment", "neutral", {"context": "Neutral tone."})
        api.section_add_item(
            did, "output_prompt_directions", "opd1", {"text": "Be concise."}
        )
        api.section_add_item(
            did, "prompt_endings", "end",
            {"name": "default", "text": "Respond helpfully."},
        )
        result = api.draft_validate(did)
        assert result["ok"] is True, result["errors"]


    def test_fragment_condition_not_in_vars_warns(self):
        did, _ = make_draft()
        api.section_add_item(did, "personas", "p1", {"context": "Base"})
        item = api.draft_get(did)["registry"]["personas"]["items"][0]
        item.setdefault("fragments", []).append(
            {"id": "f1", "text": "text", "condition": "undeclared_var"}
        )
        result = api.draft_validate(did)
        warning_paths = [w["path"] for w in result["warnings"]]
        assert any("personas" in p for p in warning_paths)

    def test_assembly_order_unknown_section_warns(self):
        did, _ = make_draft()
        api.assembly_set_order(did, ["nonexistent.text"])
        result = api.draft_validate(did)
        assert any("nonexistent" in w["message"] for w in result["warnings"])


# ── export ────────────────────────────────────────────────────────────────────

class TestExport:
    def test_export_shape(self):
        did, _ = make_draft(title="Test")
        result = api.draft_export(did)
        assert "registry" in result
        assert result["registry"]["title"] == "Test"
        assert result["registry"]["version"] == 2

    def test_export_omits_empty_optional_sections(self):
        did, _ = make_draft()
        result = api.draft_export(did)
        reg = result["registry"]
        assert "static_injections" not in reg
        assert "runtime_injections" not in reg

    def test_export_includes_populated_optional_sections(self):
        did, _ = make_draft()
        api.section_add_item(did, "static_injections", "si1", {"text": "Injected."})
        result = api.draft_export(did)
        assert "static_injections" in result["registry"]


    def test_export_preserves_assembly_order(self):
        did, _ = make_draft()
        order = ["base_context.text", "personas.context"]
        api.assembly_set_order(did, order)
        result = api.draft_export(did)
        assert result["registry"]["assembly_order"] == order


# ── var normalization edge cases ──────────────────────────────────────────────

class TestNormalization:
    def test_normalize_strips_braces(self):
        assert api._normalize_var("{foo}") == "foo"
        assert api._normalize_var("bar") == "bar"
        assert api._normalize_var("  {baz}  ") == "baz"

    def test_fragment_condition_normalized(self):
        did, _ = make_draft()
        api.section_add_item(did, "personas", "p1", {"context": "Base"})
        api.item_add_fragment(did, "personas", "p1", "f1", "text", condition="{my_var}")
        reg = api.draft_get(did)["registry"]
        frag = reg["personas"]["items"][0]["fragments"][0]
        assert frag["condition"] == "my_var"
        assert "my_var" in reg["personas"]["template_vars"]
