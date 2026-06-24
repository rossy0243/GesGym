import os

from django.utils.crypto import get_random_string
from storages.backends.s3 import S3Storage


class BackblazeMediaStorage(S3Storage):
    """
    Storage B2 compatible avec des Application Keys limitees.

    django-storages appelle normalement HeadObject pour verifier si un fichier
    existe deja. Certaines cles Backblaze limitees a l'ecriture refusent cette
    lecture et renvoient 403. On genere donc un nom unique avant l'upload sans
    preflight HeadObject.
    """

    def get_available_name(self, name, max_length=None):
        if self.file_overwrite:
            return name

        dir_name, file_name = name.rsplit("/", 1) if "/" in name else ("", name)
        file_root, file_ext = os.path.splitext(file_name)
        unique_name = f"{file_root}_{get_random_string(12)}"
        unique_name = f"{unique_name}{file_ext}"

        candidate = f"{dir_name}/{unique_name}" if dir_name else unique_name
        if max_length and len(candidate) > max_length:
            overflow = len(candidate) - max_length
            file_root = file_root[:-overflow]
            if not file_root:
                raise ValueError("Storage can not find an available filename for the upload.")
            unique_name = f"{file_root}_{get_random_string(12)}"
            unique_name = f"{unique_name}{file_ext}"
            candidate = f"{dir_name}/{unique_name}" if dir_name else unique_name

        return candidate
