import json
import os
import re
import shutil

import gevent.subprocess as subprocess


# Matches a published port mapping like:
#   0.0.0.0:8084->80/tcp
#   [::]:80->80/tcp
#   0.0.0.0:80-81->80-81/tcp   (range)
_PUBLISHED_RE = re.compile(
    r"(?P<host_ip>[0-9.]+|\[[0-9a-f:]+\]):(?P<host_port>\d+(?:-\d+)?)->"
    r"(?P<container_port>\d+(?:-\d+)?)/(?P<proto>\w+)"
)

# Hostnames in /etc/hosts we never treat as a "custom" project domain.
_BORING_HOSTS = {"localhost", "localhost.localdomain", "broadcasthost"}


def _loopback_domains():
    """Custom hostnames from /etc/hosts that point at the loopback interface.

    These are typically dev domains set up by Valet/Herd/dnsmasq style tooling
    (e.g. `robostock.test`). We use them as preferred, human-friendly targets
    when they happen to be serving a container's published port.
    """
    domains = []
    try:
        with open("/etc/hosts") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                ip, names = parts[0], parts[1:]
                if not (ip.startswith("127.") or ip == "::1"):
                    continue
                for name in names:
                    low = name.lower()
                    if low in _BORING_HOSTS or low.startswith("ip6-"):
                        continue
                    if name not in domains:
                        domains.append(name)
    except OSError:
        pass
    return domains


def _scheme_for(port: str) -> str:
    return "https" if port in ("443", "8443") else "http"


def _mk_url(scheme: str, host: str, port: str) -> str:
    # Drop the port for the scheme's default so URLs read cleanly.
    if (scheme == "http" and port == "80") or (scheme == "https" and port == "443"):
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


class DockerService:
    """Reads running containers via the `docker` CLI.

    Designed to fail soft: if docker isn't installed, the daemon is down, or the
    command errors, callers get an `available: False` payload instead of an
    exception.
    """

    def __init__(self):
        self._cli = shutil.which("docker")

    def is_available(self) -> bool:
        return self._cli is not None

    def get_containers(self) -> dict:
        if not self._cli:
            return {"available": False, "reason": "docker not installed", "containers": []}

        try:
            out = subprocess.run(
                [self._cli, "ps", "--no-trunc", "--format", "{{json .}}"],
                capture_output=True,
                text=True,
                timeout=5,
                errors="replace",
            )
        except Exception as exc:  # subprocess timeout / OS error
            return {"available": False, "reason": str(exc), "containers": []}

        if out.returncode != 0:
            reason = (out.stderr or "docker ps failed").strip().splitlines()
            reason = reason[-1] if reason else "docker ps failed"
            return {"available": False, "reason": reason, "containers": []}

        containers = []
        for line in out.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            containers.append(self._parse(raw))

        # Stable order: by compose project then name.
        containers.sort(key=lambda c: (c["project"] or "~", c["name"]))
        return {"available": True, "reason": None, "containers": containers}

    def _parse(self, raw: dict) -> dict:
        labels = self._parse_labels(raw.get("Labels", ""))
        project = labels.get("com.docker.compose.project")
        service = labels.get("com.docker.compose.service")

        name = raw.get("Names", "")
        ports = self._parse_ports(raw.get("Ports", ""), project=project, name=name)
        state = (raw.get("State") or "").lower()

        return {
            "id": (raw.get("ID") or "")[:12],
            "name": name,
            "image": raw.get("Image", ""),
            "state": state,
            "status": raw.get("Status", ""),
            "project": project,
            "service": service,
            "ports": ports,
        }

    @staticmethod
    def _parse_labels(label_str: str) -> dict:
        out = {}
        if not label_str:
            return out
        for pair in label_str.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                out[k.strip()] = v.strip()
        return out

    def _parse_ports(self, port_str: str, project=None, name=None) -> list:
        """Return de-duplicated published port mappings.

        Each mapping carries a ranked list of `candidates` (URLs to try). The
        frontend probes them in order and opens the first that responds, so a
        container that only answers on 127.0.0.1 (not the IPv6 ``localhost``) or
        that lives behind a custom dev domain like ``robostock.test`` still
        opens the right page. ``url`` stays as the single best-guess default.
        """
        if not port_str:
            return []

        custom_domains = _loopback_domains()
        seen = set()
        result = []
        for chunk in port_str.split(","):
            chunk = chunk.strip()
            m = _PUBLISHED_RE.search(chunk)
            if not m:
                continue
            host_port = m.group("host_port")
            container_port = m.group("container_port")
            proto = m.group("proto")
            key = (host_port, container_port, proto)
            if key in seen:
                continue
            seen.add(key)

            first_host_port = host_port.split("-")[0]
            candidates = self._candidate_urls(first_host_port, custom_domains, project, name)
            result.append({
                "host_port": host_port,
                "container_port": container_port,
                "proto": proto,
                "url": candidates[0] if candidates else f"http://localhost:{first_host_port}",
                "candidates": candidates,
            })
        return result

    @staticmethod
    def _candidate_urls(port: str, custom_domains, project, name) -> list:
        """Build a ranked list of URLs to try for a published host port.

        Ranking, best first:
          1. A custom /etc/hosts domain whose name matches the project/container
             (e.g. project ``robostock`` -> ``robostock.test``).
          2. 127.0.0.1 (IPv4 loopback — most reliable; browsers sometimes try
             IPv6 ``::1`` for ``localhost`` where the container isn't bound).
          3. localhost (kept as a friendly fallback).
          4. Any other custom /etc/hosts domain (last resort).
        """
        scheme = _scheme_for(port)
        ordered = []

        def add(host):
            url = _mk_url(scheme, host, port)
            if url not in ordered:
                ordered.append(url)

        # Tokens that identify this container, for fuzzy-matching dev domains.
        tokens = set()
        for src in (project, name):
            if not src:
                continue
            base = src.lower()
            tokens.add(base)
            # compose names look like "<project>-<service>-<n>"; first chunk too
            tokens.add(base.split("-")[0])
            tokens.add(base.split("_")[0])
        tokens.discard("")

        def domain_matches(domain):
            d = domain.lower()
            host_label = d.split(".")[0]
            for t in tokens:
                if t == host_label or t in d or host_label in t:
                    return True
            return False

        matching = [d for d in custom_domains if domain_matches(d)]
        others = [d for d in custom_domains if d not in matching]

        for d in matching:
            add(d)
        add("127.0.0.1")
        add("localhost")
        for d in others:
            add(d)
        return ordered
