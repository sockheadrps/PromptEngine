"""Style modulation — blend between persona/sentiment items based on emotional state.

When a ``style_blend`` config is present in the registry and emotional state is
available, the selected persona and/or sentiment items are dynamically mixed:

  - Below ``threshold``: pure primary item (no change).
  - Above ``threshold``: primary + secondary both included. The secondary
    item's group directives are sampled proportionally to blend weight so the
    pressure increases as the emotional dimension rises.

Config schema (top-level key in registry JSON alongside ``memory_config``):

    "style_blend": {
      "personas": {
        "axis": "warmth",           # which emotion dimension drives the blend
        "primary": "base_persona",  # item ID when axis is at/below threshold
        "secondary": "alt_persona", # item ID blended in as axis rises
        "threshold": 0.60           # activation point [0–1], default 0.60
      },
      "sentiment": {
        "axis": "tension",
        "primary": "calm_mode",
        "secondary": "tense_mode",
        "threshold": 0.65
      }
    }
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..registry.state import RegistryState, SectionState

if TYPE_CHECKING:
    from ..registry.model import Registry


def _blend_weight(dim_value: float, threshold: float) -> float:
    """0.0 at or below threshold; rises linearly to 1.0 at dim_value=1.0."""
    if dim_value <= threshold:
        return 0.0
    span = 1.0 - threshold
    if span <= 0.0:
        return 1.0
    return min(1.0, (dim_value - threshold) / span)


def _copy_ss(ss: SectionState) -> SectionState:
    return SectionState(
        selected=list(ss.selected) if isinstance(ss.selected, list) else ss.selected,
        slider=ss.slider,
        slider_random=ss.slider_random,
        section_random=ss.section_random,
        array_modes=dict(ss.array_modes),
        template_vars=dict(ss.template_vars),
    )


def apply_style_blend(
    state: RegistryState,
    blend_config: dict[str, Any],
    registry: "Registry",
    emotional_dims: dict[str, float],
) -> tuple[RegistryState, list[str]]:
    """Return (new_state, log) with persona/sentiment selections blended.

    The returned state is a full shallow copy of all sections. Router-attached
    attributes (_applied_rules, _rule_ending_text) are preserved.

    ``log`` is a list of human-readable strings describing what changed,
    suitable for surfacing in the ensemble trace panel.
    """
    new_sections = {k: _copy_ss(v) for k, v in state.sections.items()}
    log: list[str] = []

    for sec_key in ("personas", "sentiment"):
        cfg = blend_config.get(sec_key)
        if not cfg or not isinstance(cfg, dict):
            continue

        axis: str = cfg.get("axis") or "warmth"
        primary: str = cfg.get("primary") or ""
        secondary: str = cfg.get("secondary") or ""
        threshold: float = float(cfg.get("threshold") or 0.6)

        if not primary or not secondary:
            continue

        dim_val = float(emotional_dims.get(axis, 0.5))
        weight = _blend_weight(dim_val, threshold)

        # Ensure the section exists in new_sections.
        if sec_key not in new_sections:
            new_sections[sec_key] = SectionState(selected=primary)

        ss = new_sections[sec_key]

        if weight == 0.0:
            # Pure primary — only override if nothing is currently selected.
            if ss.selected is None:
                ss.selected = primary
            # No log entry; nothing changed.
        else:
            # Blend both items. Secondary group directives are sampled at
            # a count proportional to blend weight (minimum 1).
            ss.selected = [primary, secondary]

            sec_section = registry.sections.get(sec_key)
            if sec_section:
                sec_item = next(
                    (
                        it for it in sec_section.items
                        if (it.get("id") or it.get("name")) == secondary
                    ),
                    None,
                )
                if sec_item:
                    for group in sec_item.get("groups") or []:
                        if not isinstance(group, dict):
                            continue
                        gid = group.get("id") or group.get("name") or ""
                        if not gid:
                            continue
                        total = len(group.get("items") or [])
                        if total == 0:
                            continue
                        k = max(1, round(weight * total))
                        ss.array_modes[f"groups[{gid}]"] = f"random:{k}"

            log.append(
                f"{sec_key}: {axis}={dim_val:.2f} (>{threshold}) "
                f"{weight:.0%} blend toward \"{secondary}\""
            )

    new_state = RegistryState(sections=new_sections)
    for attr in ("_applied_rules", "_rule_ending_text"):
        if hasattr(state, attr):
            setattr(new_state, attr, getattr(state, attr))

    return new_state, log
