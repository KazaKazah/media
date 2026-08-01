import base64
import secrets

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


VERSION = "v1"


class NoteDecryptionError(ValueError):
    pass


def _fernet(password: str, salt: bytes) -> Fernet:
    if not password:
        raise ValueError("Укажите пароль для шифрования.")
    key = Scrypt(salt=salt, length=32, n=2 ** 14, r=8, p=1).derive(password.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_note(text: str, password: str) -> str:
    salt = secrets.token_bytes(16)
    token = _fernet(password, salt).encrypt(text.encode("utf-8")).decode("ascii")
    return f"{VERSION}${base64.urlsafe_b64encode(salt).decode('ascii')}${token}"


def decrypt_note(payload: str, password: str) -> str:
    try:
        version, encoded_salt, token = payload.split("$", 2)
        if version != VERSION:
            raise NoteDecryptionError("Неизвестный формат зашифрованной заметки.")
        salt = base64.urlsafe_b64decode(encoded_salt.encode("ascii"))
        return _fernet(password, salt).decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as error:
        raise NoteDecryptionError("Неверный пароль.") from error
    except NoteDecryptionError:
        raise
    except (ValueError, UnicodeDecodeError, TypeError) as error:
        raise NoteDecryptionError("Не удалось расшифровать заметку.") from error
