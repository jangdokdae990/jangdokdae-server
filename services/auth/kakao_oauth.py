"""KakaoOAuthHandler — 카카오 로그인 OAuth 흐름."""

from services.auth.oauth_handler import OAuthHandler, OAuthUserInfo


class KakaoOAuthHandler(OAuthHandler):
    provider = "kakao"
    authorize_endpoint = "https://kauth.kakao.com/oauth/authorize"
    token_endpoint = "https://kauth.kakao.com/oauth/token"
    userinfo_endpoint = "https://kapi.kakao.com/v2/user/me"

    def _normalize(self, raw: dict) -> OAuthUserInfo:
        account = raw.get("kakao_account", {})
        profile = account.get("profile", {})
        return OAuthUserInfo(
            provider=self.provider,
            provider_user_id=str(raw["id"]),
            email=account.get("email"),
            nickname=profile.get("nickname"),
            profile_image=profile.get("profile_image_url"),
        )
