"""Bounded, non-executing native X ZIP inspector.

Native layouts vary and do not prove inbound interaction coverage. This adapter
exposes a compatibility report and normalized previews, not an import guarantee.
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


class XArchiveAdapter:
    max_files = 20000
    max_section_bytes = 16 * 1024 * 1024
    max_total_bytes = 64 * 1024 * 1024
    section_pattern = re.compile(r"^(account|following|follower|followers|tweet|tweets)(?:[-_]part\d+)?\.(js|json)$", re.I)
    assignment_pattern = re.compile(r"\A\s*window\.YTD\.[A-Za-z_][A-Za-z_0-9]*\.part\d+\s*=\s*(.*?)\s*;?\s*\Z", re.S)

    def inspect(self, archive_path: str | Path) -> dict[str, Any]:
        report: dict[str, Any] = {
            "status": "UNSUPPORTED", "native_import_supported": False,
            "inspection_supported": True, "sections": {}, "missing_sections": [],
            "unsupported_files": [], "errors": [], "normalized_preview": {},
            "limitations": ["Inspection only: native ZIP import is not implemented.",
                            "No inbound replies, mentions, likes received or repost coverage is inferred.",
                            "Follower records may contain IDs without usernames; tweets alone do not establish interaction coverage."],
        }
        sections: dict[str, list[dict[str, Any]]] = {}
        total = 0
        try:
            with zipfile.ZipFile(archive_path) as archive:
                entries = archive.infolist()
                if len(entries) > self.max_files:
                    raise ValueError("Archive has too many entries")
                for info in entries:
                    name = info.filename.replace('\\', '/')
                    path = PurePosixPath(name)
                    if path.is_absolute() or '..' in path.parts or ':' in name or info.flag_bits & 1:
                        raise ValueError(f"Unsafe or encrypted ZIP member: {name}")
                    if info.is_dir():
                        continue
                    match = self.section_pattern.fullmatch(path.name)
                    if not match:
                        if path.suffix.lower() in {'.js', '.json'}:
                            report['unsupported_files'].append(name)
                        continue
                    if info.file_size > self.max_section_bytes or total + info.file_size > self.max_total_bytes:
                        raise ValueError("Archive data section exceeds inspection size limit")
                    total += info.file_size
                    section = {'follower': 'followers', 'tweet': 'tweets'}.get(match[1].lower(), match[1].lower())
                    try:
                        with archive.open(info) as stream:
                            data = stream.read(self.max_section_bytes + 1)
                        if len(data) > self.max_section_bytes:
                            raise ValueError("Section exceeds read limit")
                        text = data.decode('utf-8-sig')
                        if match[2].lower() == 'js':
                            assignment = self.assignment_pattern.fullmatch(text)
                            if assignment is None:
                                raise ValueError("Expected a single window.YTD section JSON assignment")
                            text = assignment[1]
                        rows = json.loads(text)
                        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                            raise ValueError("Expected an array of records")
                        sections.setdefault(section, []).extend(rows)
                        report['sections'].setdefault(section, {'files': [], 'records': 0})
                        report['sections'][section]['files'].append(name)
                        report['sections'][section]['records'] += len(rows)
                    except (ValueError, UnicodeError) as exc:
                        report['errors'].append(f"{name}: {exc}")
        except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
            report['errors'].append(str(exc))
        report['missing_sections'] = [key for key in ('account', 'following', 'followers', 'tweets') if key not in sections]
        preview: dict[str, list[dict[str, Any]]] = {'users': [], 'following': [], 'followers': [], 'posts': []}
        for section, rows in sections.items():
            for wrapped in rows:
                raw = wrapped.get({'followers': 'follower', 'tweets': 'tweet'}.get(section, section), wrapped)
                if not isinstance(raw, dict):
                    report['errors'].append(f"Invalid nested {section} record")
                    continue
                identity = raw.get('accountId') or raw.get('id_str') or raw.get('id')
                if identity is None:
                    report['errors'].append(f"Unrecognized {section} record identity")
                    continue
                if section == 'tweets':
                    preview['posts'].append({'id': str(identity), 'text': raw.get('full_text') or raw.get('text') or '',
                                             'created_at': raw.get('created_at')})
                else:
                    key = 'users' if section == 'account' else section
                    preview[key].append({'id': str(identity), 'username': raw.get('username') or str(identity),
                                         'name': raw.get('accountDisplayName') or ''})
        report['normalized_preview'] = preview
        if sections and not report['errors']:
            report['status'] = 'INSPECTED_PARTIAL'
        return report
