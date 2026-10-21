# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/vcs/svn_xml.py
# Architectural role: VCS infrastructure / Subversion XML parsing
# =========================================================================================

"""Structured parsers for the ``--xml`` output of the ``svn`` CLI.

Reading XML keeps the Hub independent from localized human-readable output and
from filename quoting edge cases.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from xml.etree import ElementTree


@dataclass(frozen=True)
class SvnLockInfo:
    """Repository lock metadata."""

    token: str = ""
    owner: str = ""
    comment: str = ""
    created: str = ""


@dataclass(frozen=True)
class SvnStatusEntry:
    """One entry from ``svn status --xml``."""

    path: str
    item: str = "none"
    props: str = "none"
    tree_conflicted: bool = False
    lock: Optional[SvnLockInfo] = None
    repos_item: str = "none"
    repos_props: str = "none"
    revision: str = ""

    @property
    def is_versioned(self) -> bool:
        return self.item not in ("unversioned", "ignored", "none", "external")

    @property
    def is_conflicted(self) -> bool:
        return self.tree_conflicted or self.item == "conflicted"

    @property
    def is_unversioned(self) -> bool:
        return self.item == "unversioned"

    @property
    def is_ignored(self) -> bool:
        return self.item == "ignored"

    @property
    def is_modified(self) -> bool:
        return self.item in (
            "modified",
            "added",
            "deleted",
            "replaced",
            "conflicted",
            "missing",
            "obstructed",
        ) or self.props not in ("none", "")


@dataclass(frozen=True)
class SvnInfo:
    """Selected fields from ``svn info --xml``."""

    path: str = ""
    url: str = ""
    repository_root: str = ""
    repository_uuid: str = ""
    revision: str = ""
    last_changed_revision: str = ""
    wc_root: str = ""
    lock: Optional[SvnLockInfo] = None


def _text(node: Optional[ElementTree.Element], tag: str, default: str = "") -> str:
    if node is None:
        return default
    child = node.find(tag)
    if child is None or child.text is None:
        return default
    return str(child.text).strip()


def _parse_lock(node: Optional[ElementTree.Element]) -> Optional[SvnLockInfo]:
    if node is None:
        return None
    lock = node.find("lock")
    if lock is None:
        return None
    return SvnLockInfo(
        token=_text(lock, "token"),
        owner=_text(lock, "owner"),
        comment=_text(lock, "comment"),
        created=_text(lock, "created"),
    )


def _parse_status_entry(entry: ElementTree.Element) -> SvnStatusEntry:
    wc_status = entry.find("wc-status")
    repos_status = entry.find("repos-status")
    item = wc_status.get("item", "none") if wc_status is not None else "none"
    props = wc_status.get("props", "none") if wc_status is not None else "none"
    tree_conflicted = (
        str(wc_status.get("tree-conflicted", "false")).lower() == "true"
        if wc_status is not None
        else False
    )
    lock = _parse_lock(wc_status) or _parse_lock(repos_status)
    repos_item = repos_status.get("item", "none") if repos_status is not None else "none"
    repos_props = repos_status.get("props", "none") if repos_status is not None else "none"
    revision = str(wc_status.get("revision", "")) if wc_status is not None else ""
    return SvnStatusEntry(
        path=entry.get("path", ""),
        item=item,
        props=props,
        tree_conflicted=tree_conflicted,
        lock=lock,
        repos_item=repos_item,
        repos_props=repos_props,
        revision=revision,
    )


_ITEM_TO_STATUS = {
    "modified": "M",
    "added": "A",
    "deleted": "D",
    "replaced": "R",
    "conflicted": "C",
    "missing": "!",
    "obstructed": "~",
    "unversioned": "?",
    "ignored": "I",
    "external": "X",
    "incomplete": "!",
}


def status_code(entry: SvnStatusEntry) -> str:
    """Map a structured status entry to the classic single-letter code."""
    if entry.tree_conflicted or entry.props == "conflicted" or entry.item == "conflicted":
        return "C"
    if entry.item in _ITEM_TO_STATUS:
        return _ITEM_TO_STATUS[entry.item]
    if entry.props not in ("none", ""):
        return "M"
    return " "


def parse_status_xml(xml_text: str) -> list[SvnStatusEntry]:
    """Parse ``svn status --xml`` into structured entries."""
    if not (xml_text or "").strip():
        return []
    root = ElementTree.fromstring(xml_text)
    entries: list[SvnStatusEntry] = []
    for entry in root.iter("entry"):
        entries.append(_parse_status_entry(entry))
    return entries


def parse_info_xml(xml_text: str) -> SvnInfo:
    """Parse ``svn info --xml`` into a compact value object."""
    if not (xml_text or "").strip():
        return SvnInfo()
    root = ElementTree.fromstring(xml_text)
    entry = root.find(".//entry")
    if entry is None:
        return SvnInfo()
    commit = entry.find("commit")
    return SvnInfo(
        path=entry.get("path", ""),
        url=_text(entry, "url"),
        repository_root=_text(entry, "repository/root"),
        repository_uuid=_text(entry, "repository/uuid"),
        revision=_text(entry, "revision"),
        last_changed_revision=_text(commit, "revision") if commit is not None else "",
        wc_root=_text(entry, "wc-info/wcroot-abspath"),
        lock=_parse_lock(entry),
    )


def parse_list_xml(xml_text: str) -> list[dict[str, str]]:
    """Parse ``svn list --xml`` into a list of path/kind/size mappings."""
    if not (xml_text or "").strip():
        return []
    root = ElementTree.fromstring(xml_text)
    items: list[dict[str, str]] = []
    for entry in root.iter("entry"):
        items.append(
            {
                "kind": entry.get("kind", ""),
                "name": _text(entry, "name"),
                "size": _text(entry, "size"),
                "path": entry.get("path", ""),
            }
        )
    return items


def parse_log_xml(xml_text: str) -> list[dict[str, object]]:
    """Parse ``svn log --xml`` into revision dictionaries."""
    if not (xml_text or "").strip():
        return []
    root = ElementTree.fromstring(xml_text)
    revisions: list[dict[str, object]] = []
    for entry in root.iter("logentry"):
        revisions.append(
            {
                "revision": entry.get("revision", ""),
                "author": _text(entry, "author"),
                "date": _text(entry, "date"),
                "message": _text(entry, "msg"),
                "paths": [
                    {
                        "action": path.get("action", ""),
                        "kind": path.get("kind", ""),
                        "text": (path.text or "").strip(),
                    }
                    for path in entry.findall("paths/path")
                ],
            }
        )
    return revisions
