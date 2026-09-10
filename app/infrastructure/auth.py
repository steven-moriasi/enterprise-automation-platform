from dataclasses import dataclass
from typing import Annotated, cast

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class AuthContext:
    subject: str
    roles: frozenset[str]


bearer = HTTPBearer(auto_error=False)


def _extract_roles(claims: dict[str, object]) -> frozenset[str]:
    roles: set[str] = set()
    realm_access = claims.get("realm_access")
    if isinstance(realm_access, dict):
        realm_roles = realm_access.get("roles")
        if isinstance(realm_roles, list):
            roles.update(str(role).lower() for role in realm_roles)
    direct_roles = claims.get("roles")
    if isinstance(direct_roles, list):
        roles.update(str(role).lower() for role in direct_roles)
    return frozenset(roles)


def get_auth_context(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
    x_dev_subject: Annotated[str, Header()] = "local-developer",
    x_dev_roles: Annotated[str, Header()] = "admin,operator,viewer",
) -> AuthContext:
    if not settings.auth_enabled:
        roles = frozenset(role.strip().lower() for role in x_dev_roles.split(",") if role.strip())
        return AuthContext(subject=x_dev_subject, roles=roles)

    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")

    try:
        jwks = PyJWKClient(f"{settings.oidc_issuer.rstrip('/')}/protocol/openid-connect/certs")
        signing_key = jwks.get_signing_key_from_jwt(credentials.credentials)
        claims = cast(
            dict[str, object],
            jwt.decode(
                credentials.credentials,
                signing_key.key,
                algorithms=["RS256"],
                audience=settings.oidc_audience,
                issuer=settings.oidc_issuer,
            ),
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token validation failed",
        ) from exc

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token subject missing")
    return AuthContext(subject=subject, roles=_extract_roles(claims))


def require_roles(*allowed: str):
    normalized = frozenset(role.lower() for role in allowed)

    def dependency(context: Annotated[AuthContext, Depends(get_auth_context)]) -> AuthContext:
        if context.roles.isdisjoint(normalized):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"One of these roles is required: {', '.join(sorted(normalized))}",
            )
        return context

    return dependency
