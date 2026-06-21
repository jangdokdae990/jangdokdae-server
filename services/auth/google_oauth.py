"""GoogleOAuthHandler — 구글 로그인 OAuth 흐름."""

from services.auth.oauth_handler import OAuthHandler, OAuthUserInfo


class GoogleOAuthHandler(OAuthHandler):
    provider = "google"
    authorize_endpoint = "https://accounts.google.com/o/oauth2/v2/auth"
    token_endpoint = "https://oauth2.googleapis.com/token"
    userinfo_endpoint = "https://www.googleapis.com/oauth2/v3/userinfo"
    authorize_scope = "openid email profile"

    def _normalize(self, raw: dict) -> OAuthUserInfo:
        return OAuthUserInfo(
            provider=self.provider,
            provider_user_id=str(raw["sub"]),
            email=raw.get("email"),
            nickname=raw.get("name"),
            profile_image=raw.get("picture"),
        )
