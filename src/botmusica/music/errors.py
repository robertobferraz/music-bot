from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ExtractionErrorCode(StrEnum):
    UNSUPPORTED_SOURCE = "ERR_EXTRACT_UNSUPPORTED_SOURCE"
    DRM_PROTECTED = "ERR_EXTRACT_DRM"
    PRIVATE_OR_UNAVAILABLE = "ERR_EXTRACT_UNAVAILABLE"
    FORBIDDEN = "ERR_EXTRACT_FORBIDDEN"
    RATE_LIMITED = "ERR_EXTRACT_RATE_LIMIT"
    PROVIDER_UNAVAILABLE = "ERR_PROVIDER_UNAVAILABLE"
    UNKNOWN = "ERR_EXTRACT_UNKNOWN"


@dataclass(slots=True, frozen=True)
class UserFacingError:
    code: ExtractionErrorCode
    title: str
    description: str


def map_extraction_exception(exc: Exception) -> UserFacingError:
    raw = str(exc).strip()
    lowered = raw.casefold()
    if "fonte nao suportada" in lowered:
        return UserFacingError(
            code=ExtractionErrorCode.UNSUPPORTED_SOURCE,
            title="Fonte nao suportada",
            description=(
                "Esse provedor nao oferece stream direto para o bot.\n"
                "Use uma fonte reproduzivel (ex.: YouTube, SoundCloud ou URL direta de audio)."
            ),
        )
    if "drm" in lowered and "protect" in lowered:
        return UserFacingError(
            code=ExtractionErrorCode.DRM_PROTECTED,
            title="Fonte com DRM",
            description=(
                "Esse link usa protecao DRM e nao pode ser reproduzido pelo bot.\n"
                "Use um link reproduzivel (ex.: YouTube, SoundCloud ou URL direta de audio)."
            ),
        )
    if "private" in lowered or "unavailable" in lowered:
        return UserFacingError(
            code=ExtractionErrorCode.PRIVATE_OR_UNAVAILABLE,
            title="Conteudo indisponivel",
            description="O link parece privado/indisponivel. Verifique permissao, regiao ou tente outra fonte.",
        )
    if "http error 403" in lowered or "forbidden" in lowered:
        return UserFacingError(
            code=ExtractionErrorCode.FORBIDDEN,
            title="Acesso negado pela fonte",
            description="A fonte negou acesso ao stream. Tente outro link ou outro provedor.",
        )
    if "http error 429" in lowered:
        return UserFacingError(
            code=ExtractionErrorCode.RATE_LIMITED,
            title="Limite da fonte atingido",
            description="A fonte limitou as requisicoes. Aguarde um pouco e tente novamente.",
        )
    return UserFacingError(
        code=ExtractionErrorCode.UNKNOWN,
        title="Falha ao extrair audio",
        description=f"Nao consegui extrair audio desse link:\n`{raw}`",
    )


def should_count_provider_failure(exc: Exception) -> bool:
    lowered = str(exc).strip().casefold()
    # Erros de entrada/conversao nao devem abrir o circuit breaker global.
    user_input_markers = (
        "fonte nao suportada",
        "spotify nao resolvido",
        "nenhum resultado encontrado para conversao do spotify",
        "nenhum candidato com similaridade suficiente",
        "drm",
        "private",
        "unavailable",
        "http error 403",
        "forbidden",
    )
    if any(marker in lowered for marker in user_input_markers):
        return False
    return True
