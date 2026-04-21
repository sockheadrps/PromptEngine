from __future__ import annotations

from promptlibretto import GenerationRequest, PromptEngine


async def test_section_overrides_replace_user():
    engine = PromptEngine(routes={"r": {"user_sections": ["ORIGINAL"]}})
    result = await engine.generate_once(
        GenerationRequest(mode="r", section_overrides={"user": "CUSTOM USER"})
    )
    assert "CUSTOM USER" in result.text
    assert "ORIGINAL" not in result.text


async def test_section_overrides_replace_system_and_user():
    engine = PromptEngine(routes={
        "r": {"system_sections": ["SYS A"], "user_sections": ["USER A"]}
    })
    result = await engine.generate_once(
        GenerationRequest(
            mode="r",
            section_overrides={"system": "SYS B", "user": "USER B"},
            debug=True,
        )
    )
    assert "USER B" in result.text
    assert result.trace.system_prompt == "SYS B"
    assert result.trace.user_prompt == "USER B"


async def test_section_overrides_partial_user_only():
    engine = PromptEngine(routes={
        "r": {"system_sections": ["KEEP SYS"], "user_sections": ["SKIP USER"]}
    })
    result = await engine.generate_once(
        GenerationRequest(
            mode="r",
            section_overrides={"user": "ONLY USER OVERRIDDEN"},
            debug=True,
        )
    )
    assert result.trace.system_prompt == "KEEP SYS"
    assert result.trace.user_prompt == "ONLY USER OVERRIDDEN"


async def test_section_overrides_absent_means_normal_build():
    engine = PromptEngine(routes={"r": {"user_sections": ["NORMAL"]}})
    result = await engine.generate_once(GenerationRequest(mode="r"))
    assert "NORMAL" in result.text
