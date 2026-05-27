class JangdokdaeException(Exception):
    """기본 커스텀 예외"""
    pass


class DatabaseException(JangdokdaeException):
    """데이터베이스 관련 예외"""
    pass


class AuthenticationException(JangdokdaeException):
    """인증 관련 예외"""
    pass


class NewsCollectionException(JangdokdaeException):
    """뉴스 수집 관련 예외"""
    pass


class LLMException(JangdokdaeException):
    """LLM 분석 관련 예외"""
    pass
