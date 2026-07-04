"""Unit tests for connector OAuth token encryption helpers."""

from app.core.security import decrypt_connector_token, encrypt_connector_token


def test_connector_token_round_trip() -> None:
    """Encrypting then decrypting a token returns the original value."""
    token = "ya29.a0AfB_example_access_token"
    encrypted = encrypt_connector_token(token)
    assert encrypted != token
    assert decrypt_connector_token(encrypted) == token


def test_connector_token_ciphertext_is_not_stable_plaintext() -> None:
    """Two encryptions of the same token never leak the plaintext."""
    token = "1//refresh_token_example"
    assert token not in encrypt_connector_token(token)
