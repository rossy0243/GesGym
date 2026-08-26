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
import ipaddress
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

# Bornes d'un fichier JPEG, pour extraire l'image d'une reponse multipart.
JPEG_DEBUT = bytes.fromhex("ffd8ff")
JPEG_FIN = bytes.fromhex("ffd9")

# Longueur maximale du chemin de notification acceptee par le materiel.
# Un tunnel Cloudflare inspecte la signature du client avant de transmettre.
# La signature par defaut de Python y est refusee : le lecteur repondait
# "HTTP 403 error code: 1010" sans que l'appel l'atteigne jamais.
SIGNATURE_CLIENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

URL_LONGUEUR_MAX = 128
# Le lecteur annonce hostName min=1 max=64 dans ses capacites.
HOTE_LONGUEUR_MAX = 64


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


def _corps_erreur(exc):
    """
    Message d'erreur renvoye par le lecteur.

    Hikvision explique le refus dans le corps de la reponse (statusString,
    subStatusCode). Sans lui, un HTTP 400 ne dit rien de ce qui cloche.
    """
    try:
        brut = exc.read().decode("utf-8", "replace")
    except Exception:
        return "(corps illisible)"

    texte = " ".join(brut.split())
    return texte[:400] if texte else "(corps vide)"


def _est_une_adresse_ip(hote):
    """Distingue "192.168.1.51" de "www.royalgym-fitness.com"."""
    try:
        ipaddress.ip_address(hote)
    except ValueError:
        return False
    return True


class HikvisionClient:
    """Client ISAPI minimal : lecture d'infos, test de liaison, ouverture porte."""

    def __init__(self, host, username, password, port=80, use_https=False,
                 timeout=DEFAULT_TIMEOUT, tunnel_headers=None):
        self.host = host
        self.username = username
        self.password = password
        self.port = port or 80
        self.use_https = use_https
        self.timeout = timeout
        # En-tetes exiges par le tunnel qui protege le lecteur. Sans eux,
        # l'appel est refuse avant meme d'atteindre le materiel.
        self.tunnel_headers = dict(tunnel_headers or {})

    @classmethod
    def from_device(cls, device, timeout=DEFAULT_TIMEOUT):
        return cls(
            host=device.host,
            username=device.username,
            password=device.password,
            port=device.port,
            use_https=device.use_https,
            timeout=timeout,
            tunnel_headers=device.tunnel_headers,
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
            request.add_header("User-Agent", SIGNATURE_CLIENT)
            if data is not None:
                request.add_header("Content-Type", content_type)
            if with_basic_header:
                token = base64.b64encode(
                    f"{self.username}:{self.password}".encode()
                ).decode()
                request.add_header("Authorization", f"Basic {token}")
            for nom, valeur in self.tunnel_headers.items():
                request.add_header(nom, valeur)
            return request

        try:
            response = self._opener().open(build_request(False), timeout=self.timeout)
            return response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code != 401:
                raise HikvisionError(
                    f"HTTP {exc.code} sur {path} : {_corps_erreur(exc)}"
                ) from exc
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
                raise HikvisionError(
                    f"HTTP {retry_exc.code} sur {path} : {_corps_erreur(retry_exc)}"
                ) from retry_exc
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

    # --- Fiches utilisateur et visages -------------------------------------
    #
    # Le lecteur tient sa propre base : une fiche par personne, avec ses dates
    # de validite. Il decide donc seul, meme serveur eteint. L'application
    # reste la source de verite et lui pousse ce qu'elle sait.

    FACE_LIB_TYPE = "blackFD"
    FACE_LIB_ID = "1"

    def _json(self, path, method="GET", payload=None):
        """Appel ISAPI en JSON, avec reponse decodee."""
        body = json.dumps(payload) if payload is not None else None
        brut = self.request(
            path, method=method, body=body, content_type="application/json"
        )
        try:
            return json.loads(brut) if brut.strip() else {}
        except json.JSONDecodeError as exc:
            raise HikvisionError(f"Reponse illisible sur {path} : {brut[:200]}") from exc

    def user_count(self):
        """Nombre de fiches et de visages enregistres sur le lecteur."""
        data = self._json("/ISAPI/AccessControl/UserInfo/Count?format=json")
        compte = data.get("UserInfoCount", {})
        return {
            "users": compte.get("userNumber", 0),
            "faces": compte.get("bindFaceUserNumber", 0),
            "cards": compte.get("bindCardUserNumber", 0),
        }

    def list_users(self, page_size=30):
        """Toutes les fiches presentes, page par page."""
        fiches = []
        position = 0
        # searchID doit rester stable pendant toute la pagination.
        search_id = str(uuid.uuid4())

        while True:
            data = self._json(
                "/ISAPI/AccessControl/UserInfo/Search?format=json",
                method="POST",
                payload={
                    "UserInfoSearchCond": {
                        "searchID": search_id,
                        "searchResultPosition": position,
                        "maxResults": page_size,
                    }
                },
            )
            bloc = data.get("UserInfoSearch", {})
            lot = bloc.get("UserInfo", []) or []
            fiches.extend(lot)

            position += len(lot)
            if not lot or bloc.get("responseStatusStrg") == "OK" or position >= bloc.get("totalMatches", 0):
                break

        return fiches

    def upsert_user(self, employee_no, name, begin_time, end_time, door_number=1):
        """
        Cree la fiche, ou la met a jour si elle existe deja.

        ``begin_time`` et ``end_time`` sont des chaines ISO locales, sans
        fuseau : le lecteur raisonne sur son horloge, pas sur UTC.
        """
        fiche = {
            "UserInfo": {
                "employeeNo": str(employee_no),
                "name": name[:128],
                "userType": "normal",
                "Valid": {
                    "enable": True,
                    "beginTime": begin_time,
                    "endTime": end_time,
                    "timeType": "local",
                },
                "doorRight": str(door_number),
                "RightPlan": [{"doorNo": door_number, "planTemplateNo": "1"}],
            }
        }

        # Le lecteur refuse un POST sur une fiche existante : on tente la
        # creation, puis on bascule en modification.
        try:
            return self._json(
                "/ISAPI/AccessControl/UserInfo/Record?format=json",
                method="POST",
                payload=fiche,
            )
        except HikvisionError:
            return self._json(
                "/ISAPI/AccessControl/UserInfo/Modify?format=json",
                method="PUT",
                payload=fiche,
            )

    def delete_user(self, employee_no):
        """Retire une fiche et le visage qui lui est rattache."""
        return self._json(
            "/ISAPI/AccessControl/UserInfo/Delete?format=json",
            method="PUT",
            payload={
                "UserInfoDelCond": {
                    "EmployeeNoList": [{"employeeNo": str(employee_no)}]
                }
            },
        )

    def set_face(self, employee_no, image_bytes, filename="visage.jpg"):
        """
        Rattache une photo de visage a une fiche existante.

        L'envoi est un multipart : une partie JSON qui designe la fiche, une
        partie binaire qui porte l'image. Le lecteur refuse l'image seule.
        """
        frontiere = "----smartclub" + uuid.uuid4().hex
        entete = {
            "faceLibType": self.FACE_LIB_TYPE,
            "FDID": self.FACE_LIB_ID,
            "FPID": str(employee_no),
        }

        crlf = b"\r\n"
        morceaux = [
            b"--" + frontiere.encode() + crlf,
            b'Content-Disposition: form-data; name="FaceDataRecord"' + crlf,
            b"Content-Type: application/json" + crlf + crlf,
            json.dumps(entete).encode(),
            crlf + b"--" + frontiere.encode() + crlf,
            b'Content-Disposition: form-data; name="FaceImage"; filename="'
            + filename.encode() + b'"' + crlf,
            b"Content-Type: image/jpeg" + crlf + crlf,
            image_bytes,
            crlf + b"--" + frontiere.encode() + b"--" + crlf,
        ]

        brut = self.request(
            "/ISAPI/Intelligent/FDLib/FDSetUp?format=json",
            method="PUT",
            body=b"".join(morceaux),
            content_type="multipart/form-data; boundary=" + frontiere,
        )
        try:
            return json.loads(brut) if brut.strip() else {}
        except json.JSONDecodeError:
            return {"raw": brut}

    def delete_face(self, employee_no):
        """Supprime le visage rattache a une fiche, sans toucher a la fiche."""
        return self._json(
            f"/ISAPI/Intelligent/FDLib/FDSearch/Delete?format=json"
            f"&FDID={self.FACE_LIB_ID}&faceLibType={self.FACE_LIB_TYPE}",
            method="PUT",
            payload={"FPID": [{"value": str(employee_no)}]},
        )

    # --- Messages affiches sur l'ecran du lecteur ---------------------------
    #
    # Le terminal affiche trois phrases courtes selon l'issue de la lecture.
    # Il ne sait pas les colorer : c'est du texte simple, seize caracteres au
    # plus. La voix, elle, n'est pas modifiable par cette voie.

    PROMPT_PATH = "/ISAPI/AccessControl/customPrompt?format=json"

    PROMPT_TYPES = ("stranger", "authenticationSuccess", "authenticationFailed")

    PROMPT_LONGUEUR_MAX = 16

    def get_custom_prompt(self):
        """Messages actuellement portes par le lecteur."""
        data = self._json(self.PROMPT_PATH)
        messages = {
            entree.get("promptType"): entree.get("promptContent", "")
            for entree in data.get("PromptList", [])
        }
        return {"enabled": bool(data.get("enabled")), "messages": messages}

    def set_custom_prompt(self, enabled, messages):
        """
        Ecrit les trois messages et active ou desactive leur affichage.

        Le lecteur refuse un message vide : le champ exige au moins un
        caractere. Desactiver suffit a retrouver l'affichage d'origine, il
        n'est donc pas necessaire de vider les textes.
        """
        liste = []
        for type_message in self.PROMPT_TYPES:
            contenu = (messages.get(type_message) or "").strip()
            if len(contenu) > self.PROMPT_LONGUEUR_MAX:
                raise HikvisionError(
                    f"Message trop long pour l'ecran du lecteur : "
                    f"{self.PROMPT_LONGUEUR_MAX} caracteres au maximum."
                )
            liste.append({
                "promptType": type_message,
                # Un tiret tient lieu de vide : le materiel refuse une chaine
                # vide, et le contenu ne s'affiche pas quand c'est desactive.
                "promptContent": contenu or "-",
            })

        return self._json(
            self.PROMPT_PATH,
            method="PUT",
            payload={"enabled": bool(enabled), "PromptList": liste},
        )

    def request_raw(self, path, method="GET", body=None, content_type="application/xml"):
        """
        Comme ``request``, mais rend les octets bruts.

        Indispensable quand le lecteur repond une image : decoder en texte
        detruirait le JPEG.
        """
        url = self.base_url + path
        data = body.encode("utf-8") if isinstance(body, str) else body

        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("User-Agent", SIGNATURE_CLIENT)
        if data is not None:
            request.add_header("Content-Type", content_type)
        for nom, valeur in self.tunnel_headers.items():
            request.add_header(nom, valeur)

        try:
            return self._opener().open(request, timeout=self.timeout).read()
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise HikvisionAuthError("Identifiants refuses par le lecteur.") from exc
            raise HikvisionError(
                f"HTTP {exc.code} sur {path} : {_corps_erreur(exc)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise HikvisionUnreachable(str(exc.reason)) from exc
        except (socket.timeout, TimeoutError) as exc:
            raise HikvisionUnreachable("Delai d'attente depasse.") from exc

    def capture_face(self, infrared=False):
        """
        Demande au lecteur de photographier la personne devant lui.

        La reponse est un multipart : un bloc XML portant l'avancement, puis
        l'image. Le lecteur ne rend la main qu'une fois le visage cadre, ou
        au bout de son propre delai s'il n'en trouve aucun.

        Renvoie les octets JPEG.
        """
        corps = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<CaptureFaceDataCond>"
            f"<captureInfrared>{'true' if infrared else 'false'}</captureInfrared>"
            "<dataType>binary</dataType>"
            "</CaptureFaceDataCond>"
        )
        donnees = self.request_raw(
            "/ISAPI/AccessControl/CaptureFaceData", method="POST", body=corps
        )

        debut = donnees.find(JPEG_DEBUT)
        fin = donnees.rfind(JPEG_FIN)
        if debut == -1 or fin == -1:
            # Pas d'image : le lecteur explique pourquoi dans la partie texte.
            texte = " ".join(donnees.decode("utf-8", "replace").split())
            raise HikvisionError(
                "Le lecteur n'a renvoye aucune image. "
                f"Reponse : {texte[:300] or '(vide)'}"
            )

        return donnees[debut : fin + len(JPEG_FIN)]

    def cancel_capture(self):
        """Interrompt une capture en cours, si l'operateur renonce."""
        corps = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<CaptureFaceDataCond><cancelFlag>true</cancelFlag></CaptureFaceDataCond>"
        )
        return self.request(
            "/ISAPI/AccessControl/CaptureFaceData", method="POST", body=corps
        )

    def set_event_notification(self, url, host_index=1, heartbeat=30):
        """
        Declare ou l'application ecoute, et abonne le lecteur a ses evenements.

        Deux choses distinctes, et il faut les deux : sans l'adresse le lecteur
        ne sait pas ou pousser, sans l'abonnement il connait l'adresse mais
        n'envoie rien.

        ``url`` doit etre joignable **depuis le lecteur**, donc l'adresse du
        serveur sur le reseau local, jamais 127.0.0.1.
        """
        parsed = urlparse(url)
        chemin = parsed.path or "/"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        protocole = "HTTPS" if parsed.scheme == "https" else "HTTP"
        hote = parsed.hostname or ""

        if len(chemin) > URL_LONGUEUR_MAX:
            raise HikvisionError(
                f"Chemin de notification trop long pour le lecteur "
                f"({len(chemin)} caracteres, maximum {URL_LONGUEUR_MAX})."
            )
        if len(hote) > HOTE_LONGUEUR_MAX:
            raise HikvisionError(
                f"Nom d'hote trop long pour le lecteur ({len(hote)} "
                f"caracteres, maximum {HOTE_LONGUEUR_MAX})."
            )

        # Une adresse IP et un nom de domaine ne se declarent pas de la meme
        # facon : le lecteur attend <ipAddress> pour l'une, <hostName> pour
        # l'autre, et rejette silencieusement un nom loge dans <ipAddress>.
        # C'est ce qui permet de viser le serveur public plutot qu'une adresse
        # locale qui change a chaque reseau.
        if _est_une_adresse_ip(hote):
            adressage = (
                "<addressingFormatType>ipaddress</addressingFormatType>"
                f"<ipAddress>{hote}</ipAddress>"
            )
        else:
            adressage = (
                "<addressingFormatType>hostname</addressingFormatType>"
                f"<hostName>{hote}</hostName>"
            )

        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<HttpHostNotification version="2.0">'
            f"<id>{host_index}</id>"
            f"<url>{chemin}</url>"
            f"<protocolType>{protocole}</protocolType>"
            # Le lecteur annonce "XML,JSON" : la casse compte, "json" est refuse.
            "<parameterFormatType>JSON</parameterFormatType>"
            f"{adressage}"
            f"<portNo>{port}</portNo>"
            "<httpAuthenticationMethod>none</httpAuthenticationMethod>"
            "<SubscribeEvent>"
            f"<heartbeat>{heartbeat}</heartbeat>"
            # "all" plutot que "list" : le mode liste exige d'enumerer chaque
            # sous-code d'evenement, et le lecteur refuse un <Event> qui ne
            # porte que son type. On s'abonne a tout et on filtre a l'arrivee.
            "<eventMode>all</eventMode>"
            "</SubscribeEvent>"
            "</HttpHostNotification>"
        )
        return self.request(
            f"/ISAPI/Event/notification/httpHosts/{host_index}",
            method="PUT",
            body=body,
        )

    def get_event_notification(self, host_index=1):
        """Adresse actuellement declaree, pour verifier ce que porte le lecteur."""
        brut = self.request(f"/ISAPI/Event/notification/httpHosts/{host_index}")

        def valeur(balise):
            debut = brut.find(f"<{balise}>")
            if debut == -1:
                return ""
            debut += len(balise) + 2
            return brut[debut : brut.find(f"</{balise}>", debut)].strip()

        ip = valeur("ipAddress")
        nom = valeur("hostName")
        # Le lecteur laisse "0.0.0.0" dans <ipAddress> quand il vise un nom.
        if ip in ("", "0.0.0.0") and nom:
            ip = nom

        return {
            "url": valeur("url"),
            "ip": ip,
            "hote": nom or ip,
            "port": valeur("portNo"),
            "protocole": valeur("protocolType"),
            "format": valeur("parameterFormatType"),
        }


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


# Champs ou le lecteur indique comment la personne s'est presentee. Le nom
# varie selon le firmware, on les interroge tous.
_VERIFY_MODE_KEYS = (
    "currentVerifyMode",
    "CurrentVerifyMode",
    "verifyMode",
    "VerifyMode",
    "currentVerifyModeStr",
)


def _mode_de_verification(event, payload):
    """
    Comment la personne s'est presentee : visage, badge, empreinte, code.

    Distinction essentielle : un badge et un QR code se pretent, un visage et
    une empreinte non. La regle du repassage en depend.
    """
    for source in (event, payload):
        for cle in _VERIFY_MODE_KEYS:
            valeur = source.get(cle)
            if valeur and str(valeur).strip():
                return str(valeur).strip()
    return ""


# Codes d'evenement que le materiel emploie pour une authentification par le
# visage. 75 (0x4B) est le code documente ; 8 apparait sur ce firmware pour le
# meme geste, releve sur un DS-K1T342MFWX-E1 en V4.48.40.
MINORS_VISAGE = frozenset({8, 75})


def est_un_visage(evenement):
    """
    Vrai si le lecteur a bien reconnu un visage pour ce passage.

    Trois signaux, du plus sur au moins sur :

    * ``FaceRect`` : les coordonnees du visage detecte dans l'image. C'est un
      fait physique, present uniquement quand la camera a cadre un visage ;
    * le code d'evenement, quand le firmware le renseigne ;
    * le mode de verification, seulement s'il vaut exactement "face".

    Attention a ce dernier : ``currentVerifyMode`` decrit ce que la fiche
    **autorise**, pas ce qui a **servi**. Sur ce materiel il vaut
    "faceOrFpOrCardOrPw", ce qui ne prouve rien. S'y fier seul faisait passer
    tous les visages pour des badges.
    """
    if not isinstance(evenement, dict):
        return False

    # Signal le plus fiable : la camera a localise un visage.
    if evenement.get("FaceRect") or evenement.get("faceRect"):
        return True

    minor = evenement.get("minor")
    try:
        if int(minor) in MINORS_VISAGE:
            return True
    except (TypeError, ValueError):
        pass

    mode = str(evenement.get("currentVerifyMode") or "").strip().lower()
    return mode == "face"


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
        "verify_mode": _mode_de_verification(event, payload),
        # Numero que le lecteur attribue a chaque passage. Il ne change pas
        # quand le materiel reemet la meme notification : c'est ce qui permet
        # de reconnaitre une redite.
        "event_id": str(event.get("serialNo") or payload.get("serialNo") or ""),
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
