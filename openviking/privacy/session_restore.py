# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""Restore user-owned references only at the public Session content boundary."""

import json
import re

from openviking.privacy.reference import PrivacyFieldReference
from openviking.privacy.restore import PrivacyRestorer, restore_text
from openviking.privacy.service import UserPrivacyConfigService
from openviking.privacy.session_extractor import session_privacy_target
from openviking.server.identity import RequestContext
from openviking_cli.exceptions import InvalidArgumentError

_SESSION_REFERENCE = re.compile(
    r"\{\{[ \t]*ov_privacy:session:([A-Za-z0-9_.@-]+):([A-Za-z0-9_-]{8})[ \t]*\}\}"
)
_TEXT_FIELDS = {
    "text": ("text",),
    "context": ("abstract",),
    "tool": ("tool_output", "tool_output_externalization_error"),
}


def get_session_id_from_uri(uri: str, session_root: str) -> str | None:
    prefix = session_root + "/"
    if not uri.startswith(prefix):
        return None
    session_id, *path = uri[len(prefix) :].split("/")
    if not session_id:
        return None
    if path == ["messages.jsonl"]:
        return session_id
    if len(path) == 3 and path[0] == "history" and path[1].startswith("archive_"):
        return session_id if path[2] == "messages.jsonl" else None
    if len(path) == 3 and path[0] == "tool-results" and path[2] == "output.txt":
        return session_id
    return None


async def restore_session_content(
    privacy: UserPrivacyConfigService,
    content: str,
    ctx: RequestContext,
    *,
    session_id: str,
    jsonl: bool = False,
) -> str:
    """Resolve user-owned references from current values without rewriting disk."""
    target_key = session_privacy_target(session_id)
    references = {
        match[0]: PrivacyFieldReference(ctx.user.user_id, "session", target_key, match[2])
        for match in _SESSION_REFERENCE.finditer(content)
        if match[1] == target_key
    }
    restorer = PrivacyRestorer(privacy, ctx)
    resolved = await restorer.resolve(content, references)
    if not resolved:
        return content
    if not jsonl:
        return restore_text(content, resolved)

    def structured(value):
        if isinstance(value, str):
            if value in resolved:
                return resolved[value]
            return restore_text(value, resolved)
        if isinstance(value, list):
            return [structured(item) for item in value]
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                clean_key = restore_text(key, resolved)
                if clean_key in result:
                    raise InvalidArgumentError("Session privacy restored object key collision")
                result[clean_key] = structured(item)
            return result
        return value

    lines = []
    for line in content.split("\n"):
        if not line.strip():
            lines.append(line)
            continue
        try:
            message = json.loads(line)
            for part in message.get("parts", []):
                for field in _TEXT_FIELDS.get(part.get("type"), ()):
                    if isinstance(part.get(field), str):
                        part[field] = restore_text(part[field], resolved)
                if part.get("type") == "tool" and "tool_input" in part:
                    part["tool_input"] = structured(part["tool_input"])
        except (ValueError, TypeError, AttributeError):
            raise InvalidArgumentError("Session privacy requires valid message JSONL") from None
        lines.append(json.dumps(message, ensure_ascii=False))
    return "\n".join(lines)
