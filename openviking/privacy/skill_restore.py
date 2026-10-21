# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""Read-time restore helpers for skill privacy placeholders."""

import re

from openviking.privacy.reference import PrivacyFieldReference
from openviking.privacy.restore import PrivacyRestorer, restore_text
from openviking.privacy.service import UserPrivacyConfigService
from openviking.server.identity import RequestContext


def get_skill_name_from_uri(uri: str) -> str | None:
    normalized = uri.strip().rstrip("/")
    marker = "/skills/"
    suffix = "/SKILL.md"
    if marker not in normalized or not normalized.endswith(suffix):
        return None
    start = normalized.rfind(marker)
    if start < 0:
        return None
    middle = normalized[start + len(marker) : -len(suffix)]
    if not middle or "/" in middle:
        return None
    return middle


async def restore_skill_content(
    privacy: UserPrivacyConfigService,
    content: str,
    ctx: RequestContext,
    *,
    skill_name: str,
) -> str:
    pattern = re.compile(r"\{\{ov_privacy:skill:" + re.escape(skill_name) + r":([^}:]+)\}\}")
    references = {
        match[0]: PrivacyFieldReference(ctx.user.user_id, "skill", skill_name, match[1])
        for match in pattern.finditer(content)
    }
    restorer = PrivacyRestorer(privacy, ctx)
    resolved = await restorer.resolve(content, references)
    current = await restorer.get_current("skill", skill_name)
    values = current.values if current else {}
    unresolved_entries: list[str] = []

    for selector, reference in references.items():
        raw_value = values.get(reference.field)
        if raw_value is None or raw_value == "":
            shown_value = "<missing>" if raw_value is None else '""'
            unresolved_entries.append(f"{reference.field}={shown_value}")
            resolved.pop(selector, None)

    used_fields = {
        reference.field
        for reference in restorer.references.values()
        if reference.category == "skill" and reference.target_key == skill_name
    }
    extra_config_entries = [
        f"{key}={value}"
        for key, value in values.items()
        if key not in used_fields and value is not None and value != ""
    ]

    restored = restore_text(content, resolved)
    if current and (unresolved_entries or extra_config_entries):
        restored += "\n\n[Privacy Config Notice]\n"
        if unresolved_entries:
            restored += "Missing config: " + ", ".join(unresolved_entries) + "\n"
        if extra_config_entries:
            restored += (
                "Configured but not referenced in content: "
                + ", ".join(extra_config_entries)
                + "\n"
            )

    return restored
