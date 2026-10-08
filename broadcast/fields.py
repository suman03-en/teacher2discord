"""
Custom model fields for the broadcast app.
"""

from django.db import models

from .crypto import decrypt_value, encrypt_value


class EncryptedTextField(models.TextField):
    """A TextField that transparently encrypts data at rest.

    * On **save** the plaintext is Fernet-encrypted and prefixed so that
      it can be identified later.
    * On **load** the prefix is detected and the value is decrypted back
      to plaintext.
    * Values that are *not* prefixed (e.g. legacy plaintext rows) are
      returned as-is, allowing a gradual migration.

    .. warning::
       Because encryption is non-deterministic (Fernet uses a random IV),
       ``filter(field=value)`` will **not** match.  Use a companion hash
       field for indexed lookups instead.
    """

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        return decrypt_value(value)

    def get_prep_value(self, value):
        if value is None:
            return value
        return encrypt_value(value)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        # Return the canonical import path so migrations are portable.
        return name, "broadcast.fields.EncryptedTextField", args, kwargs
