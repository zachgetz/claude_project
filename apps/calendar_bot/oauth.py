from decouple import config
from google_auth_oauthlib.flow import Flow

SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events',
]


def get_oauth_flow(redirect_uri=None):
    """
    Build and return a Google OAuth2 Flow using GOOGLE_CLIENT_ID and
    GOOGLE_CLIENT_SECRET from environment variables.
    """
    client_config = {
        'web': {
            'client_id': config('GOOGLE_CLIENT_ID'),
            'client_secret': config('GOOGLE_CLIENT_SECRET'),
            'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
            'token_uri': 'https://oauth2.googleapis.com/token',
            'redirect_uris': [redirect_uri] if redirect_uri else [],
        }
    }

    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    return flow
