"""
Configuration du serveur applicatif.

Sa seule raison d'etre : taire les sondes de sante dans le journal d'acces. La
regle elle-meme vit dans ``core.log_filtering``, ou elle est testable - ce
fichier n'est jamais importe ailleurs qu'en production.
"""

from gunicorn.glogging import Logger

from core.log_filtering import doit_journaliser


class LoggerSansSondes(Logger):
    def access(self, resp, req, environ, request_time):
        if not doit_journaliser(environ.get("PATH_INFO", "")):
            return
        super().access(resp, req, environ, request_time)


logger_class = LoggerSansSondes
