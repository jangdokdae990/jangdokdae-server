"""NaverOAuthHandler — 네이버 로그인 OAuth 흐름.

네이버는 authorize·token 모두 state가 필수이고, userinfo를 'response' 키로 한 번 감싼다.
"""

from services.auth.oauth_handler import OAuthHandler, OAuthUserInfo


class NaverOAuthHandler(OAuthHandler):
    provider = "naver"
    authorize_endpoint = "https://nid.naver.com/oauth2.0/authorize"
    token_endpoint = "https://nid.naver.com/oauth2.0/token"
    userinfo_endpoint = "https://openapi.naver.com/v1/nid/me"

    def _normalize(self, raw: dict) -> OAuthUserInfo:
        response = raw.get("response", {})
        return OAuthUserInfo(
            provider=self.provider,
            provider_user_id=str(response["id"]),
            email=response.get("email"),
            nickname=response.get("nickname"),
            profile_image=response.get("profile_image"),
        )
