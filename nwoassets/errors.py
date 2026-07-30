class NwoAssetsError(Exception):
    """Erro esperado, apropriado para ser exibido pela CLI."""


class FormatError(NwoAssetsError):
    """Arquivo truncado, inconsistente ou em formato não suportado."""


class ProfileError(NwoAssetsError):
    """O conjunto de assinaturas não corresponde a um perfil conhecido."""

