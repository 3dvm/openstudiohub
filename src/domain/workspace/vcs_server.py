# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/workspace/vcs_server.py
# Architectural role: Workspace value objects (VCS server registry)
# =========================================================================================

"""Named VCS servers.

A studio can host several version-control backends (a local Docker sandbox for
development, one or more production VPS over the tailnet, ...). Each project is
bound to exactly one server through its blueprint. This module models that
registry independently from the persistence layer.
"""

import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Optional, Tuple

from .vcs_server_profile import LOCAL_DOCKER, VCSServerProfile

VALID_ADAPTERS = ("svn", "git-lfs", "none")

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """Human-readable, URL/JSON-safe identifier for a server."""
    slug = _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-")
    return slug or "server"


@dataclass(frozen=True)
class VCSServer:
    """A single VCS backend the Hub can operate against."""

    id: str
    name: str
    adapter: str = "svn"
    repository_url: str = ""
    enable_vendor_sparse_checkout: bool = True
    profile: VCSServerProfile = field(default_factory=VCSServerProfile)

    @property
    def is_enabled(self) -> bool:
        return (self.adapter or "none").lower() != "none"

    @property
    def is_remote(self) -> bool:
        return self.profile.mode != LOCAL_DOCKER

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "VCSServer":
        data = data or {}
        name = (data.get("name") or "Server").strip() or "Server"
        server_id = (data.get("id") or slugify(name)).strip() or slugify(name)
        adapter = (data.get("adapter") or "svn").strip().lower()
        if adapter not in VALID_ADAPTERS:
            adapter = "svn"
        return cls(
            id=server_id,
            name=name,
            adapter=adapter,
            repository_url=(data.get("repository_url") or "").strip(),
            enable_vendor_sparse_checkout=bool(data.get("enable_vendor_sparse_checkout", True)),
            profile=VCSServerProfile.from_dict(data.get("profile")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "adapter": self.adapter,
            "repository_url": self.repository_url,
            "enable_vendor_sparse_checkout": self.enable_vendor_sparse_checkout,
            "profile": self.profile.to_dict(),
        }


@dataclass(frozen=True)
class VCSServerRegistry:
    """Ordered collection of servers plus the studio default."""

    servers: Tuple[VCSServer, ...] = ()
    default_server_id: str = ""

    def get(self, server_id: str) -> Optional[VCSServer]:
        if not server_id:
            return None
        for server in self.servers:
            if server.id == server_id:
                return server
        return None

    def get_by_url(self, repository_url: str) -> Optional[VCSServer]:
        target = (repository_url or "").rstrip("/")
        if not target:
            return None
        for server in self.servers:
            if server.repository_url.rstrip("/") == target:
                return server
        return None

    def default(self) -> Optional[VCSServer]:
        return self.get(self.default_server_id) or (self.servers[0] if self.servers else None)

    def resolve(self, vcs_server_id: str = "", vcs_base_url: str = "") -> Optional[VCSServer]:
        """Best-effort binding: explicit id, then URL match, then the default."""
        return self.get(vcs_server_id) or self.get_by_url(vcs_base_url) or self.default()

    def with_server(self, server: VCSServer) -> "VCSServerRegistry":
        servers = [s for s in self.servers if s.id != server.id]
        servers.append(server)
        default_id = self.default_server_id or server.id
        return replace(self, servers=tuple(servers), default_server_id=default_id)

    def without_server(self, server_id: str) -> "VCSServerRegistry":
        servers = tuple(s for s in self.servers if s.id != server_id)
        default_id = self.default_server_id
        if default_id == server_id:
            default_id = servers[0].id if servers else ""
        return replace(self, servers=servers, default_server_id=default_id)

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "VCSServerRegistry":
        data = data or {}
        raw_servers = data.get("servers") or []
        servers = tuple(VCSServer.from_dict(item) for item in raw_servers if isinstance(item, dict))
        default_id = (data.get("default_server_id") or "").strip()
        if default_id and not any(s.id == default_id for s in servers):
            default_id = servers[0].id if servers else ""
        if not default_id and servers:
            default_id = servers[0].id
        return cls(servers=servers, default_server_id=default_id)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "servers": [server.to_dict() for server in self.servers],
            "default_server_id": self.default_server_id,
        }
