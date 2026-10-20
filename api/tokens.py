from datetime import UTC, datetime

import jwt
from pydantic import ValidationError

from api.settings import _Settings
from models.exceptions.access import AuthenticationFailed
from models.pydantic.auth import AuthenticatedUser, TokenClaims, TokenResponse


class Tokens:
    def __init__(self, *, config: _Settings) -> None:
        self._secret = config.APP_AUTH_TOKEN_SECRET.get_secret_value()
        self._ttl_sec = config.APP_AUTH_TOKEN_TTL_SEC
        self._issuer = config.APP_AUTH_TOKEN_ISSUER
        self._audience = config.APP_AUTH_TOKEN_AUDIENCE

    def issue(self, user: AuthenticatedUser) -> TokenResponse:
        now = int(datetime.now(UTC).timestamp())
        claims = TokenClaims(
            sub=user.id, ver=user.token_version, iat=now, exp=now + self._ttl_sec, iss=self._issuer, aud=self._audience
        )
        return TokenResponse(
            access_token=jwt.encode(claims.model_dump(mode="json"), self._secret, algorithm="HS256"),
            expires_in=self._ttl_sec,
        )

    def decode(self, token: str) -> TokenClaims:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["sub", "ver", "iat", "exp", "iss", "aud"]},
            )
            return TokenClaims.model_validate(payload)
        except (jwt.InvalidTokenError, ValidationError) as exc:
            raise AuthenticationFailed() from exc
