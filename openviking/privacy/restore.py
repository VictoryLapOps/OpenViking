# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""Resolve Privacy references to the current user's active values."""

import re
from typing import Any

from openviking.privacy.models import UserPrivacyConfigVersion
from openviking.privacy.reference import PrivacyFieldReference, parse_privacy_field_reference
from openviking.privacy.service import UserPrivacyConfigService
from openviking.server.identity import RequestContext
from openviking_cli.exceptions import InvalidArgumentError, NotFoundError, ResourceExhaustedError

_REFERENCE = re.compile(r"\{\{[ \t]*ov_privacy:[^{}\r\n]+\}\}")
MAX_RESTORE_TARGETS = 1024


class PrivacyRestorer:
    """Resolve references with a configuration cache scoped to one read."""

    def __init__(self, privacy: UserPrivacyConfigService, ctx: RequestContext):
        self._privacy = privacy
        self._ctx = ctx
        self._configs: dict[tuple[str, str], UserPrivacyConfigVersion | None] = {}
        self.references: dict[str, PrivacyFieldReference] = {}

    async def get_current(self, category: str, target_key: str) -> UserPrivacyConfigVersion | None:
        target = (category, target_key)
        if target not in self._configs:
            try:
                self._configs[target] = await self._privacy.get_current(
                    self._ctx, category, target_key
                )
            except (NotFoundError, FileNotFoundError, InvalidArgumentError):
                self._configs[target] = None
        return self._configs[target]

    async def resolve(
        self, content: str, local_references: dict[str, PrivacyFieldReference]
    ) -> dict[str, Any]:
        """Retain owned references and resolve their fields from active configs."""
        self.references = {}
        targets = set()
        for match in _REFERENCE.finditer(content):
            selector = match[0]
            if selector in self.references:
                continue
            reference = local_references.get(selector) or parse_privacy_field_reference(selector)
            if reference is None or reference.owner_user_id != self._ctx.user.user_id:
                continue
            targets.add((reference.category, reference.target_key))
            if len(targets) > MAX_RESTORE_TARGETS:
                raise ResourceExhaustedError("Privacy reference target limit exceeded")
            self.references[selector] = reference

        resolved = {}
        for selector, reference in self.references.items():
            current = await self.get_current(reference.category, reference.target_key)
            if current is not None and reference.field in current.values:
                resolved[selector] = current.values[reference.field]
        return resolved


def restore_text(content: str, resolved: dict[str, Any]) -> str:
    """Replace original occurrences once, leaving inserted references untouched."""
    if not resolved:
        return content
    return _REFERENCE.sub(
        lambda match: str(resolved[match[0]]) if match[0] in resolved else match[0], content
    )
