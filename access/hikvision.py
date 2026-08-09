"""
Integration des lecteurs de controle d'acces Hikvision (protocole ISAPI).

Deux briques independantes :

* ``discover_devices()`` : decouverte SADP en multicast UDP. Permet a l'app de
  proposer les lecteurs presents sur le reseau sans rien saisir a la main.
* ``HikvisionClient`` : client ISAPI (HTTP + authentification digest) pour
  interroger un lecteur, tester la liaison et ouvrir la porte a distance.

Aucune dependance externe : uniquement la bibliotheque standard.
"""

import base64
import json
import socket
import struct
import time
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

SADP_GROUP = "239.255.255.250"
SADP_PORT = 37020

DEFAULT_TIMEOUT = 6
DISCOVERY_TIMEOUT = 4

# Marques supportees pour l'instant.
BRAND_HIKVISION = "hikvision"


class HikvisionError(Exception):
    """Erreur de dialogue avec un lecteur."""


class HikvisionAuthError(HikvisionError):
    """Identifiants refuses par le lecteur."""


class HikvisionUnreachable(HikvisionError):
    """Lecteur injoignable sur le reseau."""


# ---------------------------------------------------------------------------
# Decouverte SADP
# ---------------------------------------------------------------------------

_PROBE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    "<Probe><Uuid>{uuid}</Uuid><Types>inquiry</Types></Probe>"
)


def _local_ipv4_addresses():
    """Adresses IPv4 locales utilisables pour emettre la sonde multicast."""
    addresses = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addresses.add(info[4][0])
    except socket.gaierror:
        pass

    # Repli : l'adresse utilisee pour sortir sur le reseau.
    probe_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe_socket.connect(("8.8.8.8", 80))
        addresses.add(probe_socket.getsockname()[0])
    except OSError:
        pass
    finally:
        probe_socket.close()

    addresses.discard("127.0.0.1")
    return sorted(addresses)


def _sadp_socket(local_ip):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("", SADP_PORT))
    except OSError:
        # Port occupe (outil SADP ouvert) : on ecoute sur un port ephemere.
        sock.bind(("", 0))

    mreq = struct.pack("4s4s", socket.inet_aton(SADP_GROUP), socket.inet_aton(local_ip))
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    except OSError:
        pass
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(local_ip))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(0.4)
    return sock


def _parse_probe_match(payload):
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return None

    if not root.tag.endswith("ProbeMatch"):
        return None

    return {child.tag.split("}")[-1]: (child.text or "").strip() for child in root}


def discover_devices(timeout=DISCOVERY_TIMEOUT):
    """
    Renvoie la liste des equipements Hikvision qui repondent a la sonde SADP.

    Chaque entree : host, mac, model, serial, firmware, http_port, activated,
    dhcp, subnet_mask, gateway.
    """
    probe = _PROBE.format(uuid=str(uuid.uuid4()).upper()).encode()
    sockets = []

    for local_ip in _local_ipv4_addresses():
        try:
            sock = _sadp_socket(local_ip)
        except OSError:
            continue
        sockets.append(sock)
        for _ in range(3):
            try:
                sock.sendto(probe, (SADP_GROUP, SADP_PORT))
            except OSError:
                break

    if not sockets:
        return []

    found = {}
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            for sock in sockets:
                try:
                    data, addr = sock.recvfrom(8192)
                except (socket.timeout, OSError):
                    continue

                raw = _parse_probe_match(data)
                if not raw:
                    continue

                host = raw.get("IPv4Address") or addr[0]
                mac = (raw.get("MAC") or "").upper()
                found[mac or host] = {
                    "host": host,
                    "mac": mac,
                    "model": raw.get("DeviceDescription") or raw.get("DeviceType") or "",
                    "serial": raw.get("DeviceSN") or "",
                    "firmware": raw.get("SoftwareVersion") or "",
                    "http_port": int(raw.get("HttpPort") or 80),
                    "activated": (raw.get("Activated") or "").lower() == "true",
                    "dhcp": (raw.get("DHCP") or "").lower() == "true",
                    "subnet_mask": raw.get("IPv4SubnetMask") or "",
                    "gateway": raw.get("IPv4Gateway") or "",
                }
    finally:
        for sock in sockets:
            sock.close()

    return sorted(found.values(), key=lambda item: item["host"])


def scan_subnet(base, port=80, timeout=0.3, max_workers=128):
    """
    Repli quand le multicast est filtre (Wi-Fi, VLAN) : balayage TCP du /24.

    ``base`` est le prefixe reseau, par exemple "192.168.1".
    Renvoie les hotes dont le port HTTP repond et qui exposent ISAPI.
    """
    from concurrent.futures import ThreadPoolExecutor

    def probe(host):
        sock = socket.socket()
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
        except OSError:
            return None
        finally:
            sock.close()

        # Un endpoint ISAPI repond 401 sans identifiants : signature suffisante.
        request = urllib.request.Request(f"http://{host}:{port}/ISAPI/System/deviceInfo")
        try:
            urllib.request.urlopen(request, timeout=2)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                return {"host": host, "http_port": port, "isapi": True}
            return None
        except OSError:
            return None
        return {"host": host, "http_port": port, "isapi": True}

    hosts = [f"{base}.{index}" for index in range(1, 255)]
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for outcome in pool.map(probe, hosts):
            if outcome:
                results.append(outcome)
    return results


# ---------------------------------------------------------------------------
# Client ISAPI
# ---------------------------------------------------------------------------


class HikvisionClient:
    """Client ISAPI minimal : lecture d'infos, test de liaison, ouverture porte."""

    def __init__(self, host, username, password, port=80, use_https=False, timeout=DEFAULT_TIMEOUT):
        self.host = host
        self.username = username
        self.password = password
        self.port = port or 80
        self.use_https = use_https
        self.timeout = timeout

    @classmethod
    def from_device(cls, device, timeout=DEFAULT_TIMEOUT):
        return cls(
            host=device.host,
            username=device.username,
            password=device.password,
            port=device.port,
            use_https=device.use_https,
            timeout=timeout,
        )

    @property
    def base_url(self):
        scheme = "https" if self.use_https else "http"
        if (self.use_https and self.port == 443) or (not self.use_https and self.port == 80):
            return f"{scheme}://{self.host}"
        return f"{scheme}://{self.host}:{self.port}"

    def _opener(self):
        manager = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        manager.add_password(None, self.base_url, self.username, self.password)
        return urllib.request.build_opener(
            urllib.request.HTTPDigestAuthHandler(manager),
            urllib.request.HTTPBasicAuthHandler(manager),
        )

    def request(self, path, method="GET", body=None, content_type="application/xml"):
        """Execute un appel ISAPI et renvoie le corps de reponse en texte."""
        url = self.base_url + path
        data = body.encode("utf-8") if isinstance(body, str) else body

        def build_request(with_basic_header):
            request = urllib.request.Request(url, data=data, method=method)
            if data is not None:
                request.add_header("Content-Type", content_type)
            if with_basic_header:
                token = base64.b64encode(
                    f"{self.username}:{self.password}".encode()
                ).decode()
                request.add_header("Authorization", f"Basic {token}")
            return request

        try:
            response = self._opener().open(build_request(False), timeout=self.timeout)
            return response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code != 401:
                raise HikvisionError(f"HTTP {exc.code} sur {path}") from exc
            # Certains firmwares n'acceptent que le Basic preemptif.
            try:
                response = urllib.request.urlopen(
                    build_request(True), timeout=self.timeout
                )
                return response.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as retry_exc:
                if retry_exc.code == 401:
                    raise HikvisionAuthError(
                        "Identifiants refuses par le lecteur."
                    ) from retry_exc
                raise HikvisionError(f"HTTP {retry_exc.code} sur {path}") from retry_exc
            except urllib.error.URLError as retry_exc:
                raise HikvisionUnreachable(str(retry_exc.reason)) from retry_exc
        except urllib.error.URLError as exc:
            raise HikvisionUnreachable(str(exc.reason)) from exc
        except (socket.timeout, TimeoutError) as exc:
            raise HikvisionUnreachable("Delai d'attente depasse.") from exc

    def device_info(self):
        """Modele, numero de serie, firmware et nom du lecteur."""
        payload = self.request("/ISAPI/System/deviceInfo")
        try:
            root = ET.fromstring(payload)
        except ET.ParseError as exc:
            raise HikvisionError("Reponse deviceInfo illisible.") from exc

        def value(tag):
            node = root.find(f"{{*}}{tag}")
            if node is None:
                node = root.find(tag)
            return (node.text or "").strip() if node is not None else ""

        return {
            "name": value("deviceName"),
            "model": value("model"),
            "serial": value("serialNumber"),
            "firmware": value("firmwareVersion"),
            "mac": value("macAddress").upper(),
        }

    def capabilities(self):
        """Capacites de controle d'acces (modes de verification, QR, portes)."""
        return self.request("/ISAPI/AccessControl/capabilities")

    def open_door(self, door_number=1):
        """Ouverture distante du relais de porte."""
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<RemoteControlDoor><cmd>open</cmd></RemoteControlDoor>"
        )
        return self.request(
            f"/ISAPI/AccessControl/RemoteControl/door/{door_number}",
            method="PUT",
            body=body,
        )

    def set_event_notification(self, url, protocol="HTTP", host_index=1):
        """
        Declare l'URL de notification vers laquelle le lecteur pousse ses evenements.

        ``url`` doit etre joignable depuis le lecteur (adresse LAN du serveur).
        """
        parsed = urlparse(url)

        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<HttpHostNotification version="2.0">'
            f"<id>{host_index}</id>"
            "<url>{path}</url>"
            "<protocolType>{protocol}</protocolType>"
            "<parameterFormatType>json</parameterFormatType>"
            "<addressingFormatType>ipaddress</addressingFormatType>"
            "<ipAddress>{ip}</ipAddress>"
            "<portNo>{port}</portNo>"
            "<httpAuthenticationMethod>none</httpAuthenticationMethod>"
            "</HttpHostNotification>"
        ).format(
            path=parsed.path or "/",
            protocol=protocol,
            ip=parsed.hostname or "",
            port=parsed.port or (443 if parsed.scheme == "https" else 80),
        )
        return self.request(
            f"/ISAPI/Event/notification/httpHosts/{host_index}",
            method="PUT",
            body=body,
        )


# ---------------------------------------------------------------------------
# Evenements pousses par le lecteur
# ---------------------------------------------------------------------------

# Champs ou Hikvision place l'identifiant presente selon le mode (QR, carte, badge).
_CREDENTIAL_KEYS = (
    "QRCodeInfo",
    "qrCodeInfo",
    "QRCode",
    "qrCode",
    "cardNo",
    "CardNo",
    "employeeNoString",
    "employeeNo",
)


def parse_event_payload(raw_body, content_type=""):
    """
    Extrait les donnees utiles d'une notification poussee par le lecteur.

    Le lecteur envoie soit du JSON, soit un multipart contenant un bloc JSON/XML
    et parfois une image. On isole le bloc structure et on en tire l'identifiant
    presente (contenu du QR code ou numero de carte).
    """
    text = raw_body.decode("utf-8", "replace") if isinstance(raw_body, bytes) else raw_body

    payload = None
    if "json" in (content_type or "").lower() or text.lstrip().startswith("{"):
        payload = _safe_json(text)

    if payload is None:
        # Multipart : on recupere le premier objet JSON complet du corps.
        start = text.find("{")
        while start != -1 and payload is None:
            payload = _safe_json(_balanced_json(text, start))
            start = text.find("{", start + 1)

    if payload is None:
        return {"credential": "", "event": {}, "raw": text[:2000]}

    event = payload.get("AccessControllerEvent") or payload.get("accessControllerEvent") or {}

    credential = ""
    for source in (event, payload):
        for key in _CREDENTIAL_KEYS:
            value = source.get(key)
            if value and str(value).strip() not in ("", "0"):
                credential = str(value).strip()
                break
        if credential:
            break

    return {
        "credential": credential,
        "event": event,
        "payload": payload,
        "raw": text[:2000],
    }


def _safe_json(text):
    if not text:
        return None
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _balanced_json(text, start):
    """Renvoie la sous-chaine JSON equilibree qui demarre a ``start``."""
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""
