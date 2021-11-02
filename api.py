from typing import Generator
from bs4 import BeautifulSoup
from shutil import copyfileobj

import requests
import re
import json
import time
import urllib.parse
import random
import os

def _javascript_parser(html: str, script_type="window._sharedData = ") -> dict:
    """Parse html for javascript json data."""
    parser = BeautifulSoup(html, "html.parser")
    body = parser.find("body")
    script = body.find("script", text=re.compile(script_type))
    script = script.get_text().replace(script_type.replace('\\', ""), "")
    return json.loads(script[:script.rfind('}') + 1])

class CSRFTokenError(Exception):
    pass

class Media:
    def __init__(self, metadata: dict) -> None:
        self._metadata = metadata
        self.id: str = metadata["id"]
        self.is_video: bool = metadata["is_video"]
        self.src: str = metadata['display_url']
        if self.is_video:
            self.src = metadata["video_url"]
            self.video_view_count: int = metadata["video_view_count"]
            self.video_play_count: int = metadata["video_play_count"]
            self.video_duration: float = metadata["video_duration"]
        self.filename: str = (self.src.split('?')[0]).split('/')[-1]

    def download(self, local_path: str) -> None:
        if not os.path.exists:
            os.makedirs(local_path)
        response = requests.get(self.src, stream=True)
        with open(os.path.join(local_path, self.filename), 'wb') as content:
            copyfileobj(response.raw, content)
        del response

class GraphQLAPI:
    IG_HOSTNAME = "https://www.instagram.com/"
    QUERY_HASH_POSTS = "f2405b236d85e8296cf30347c9f08c2a"
    QUERY_HASH_ALL_REEL_TYPES = "d4d88dc1500312af6f937f7b804c68c3"
    QUERY_HASH_HIGHLIGHT_REELS = "303a4ae99711322310f25250d988f3b7"

    def __init__(self, username: str, password: str) -> None:
        super().__init__()
        self._username = username
        self._password = password
        self._user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:86.0) Gecko/20100101 Firefox/86.0"
        self._authentication_status: dict = None
        self._profile_id = None
        self._profile_metadata = None
        self._profile_username = None

    def authenticate(self) -> None:
        """Login into Instagram."""
        referer = self.IG_HOSTNAME + "accounts/login/"
        self._session = requests.Session()
        self._session.headers.update({"user-agent": self._user_agent})
        html = self._session.get(referer, headers={"Referer": referer})
        data = _javascript_parser(html.content)
        try:
            csrf_token = data["config"]["csrf_token"]
        except IndexError:
            raise CSRFTokenError("Error retrieving csrf auth token.")
        auth_data = {
            "username": self._username, 
            "enc_password": f"#PWD_INSTAGRAM_BROWSER:0:{time.time()}:{self._password}"
        }
        response = self._session.post(
            referer + "ajax/", data=auth_data, 
            headers={"X-CSRFToken": csrf_token}, 
            allow_redirects=True
        )
        self._authentication_status = json.loads(response.content.decode())

    def is_authenticated(self) -> bool:
        """Checks if user was successfully authenticated."""
        if self._authentication_status['authenticated']:
            return True
        return False

    def _graphql_profile(self, profile_username: str) -> None:
        """Get profile provided."""
        response = self._session.get(self.IG_HOSTNAME + profile_username)
        result = _javascript_parser(response.content)
        self._profile_metadata = result["entry_data"]["ProfilePage"][0]["graphql"]["user"]
        self._profile_id = self._profile_metadata["id"]
        self._profile_username = profile_username

    def _graphql_profile_posts(self) -> Generator[Media, None, None]:
        """Parse graphql data for all posts"""
        timeline = self._profile_metadata["edge_owner_to_timeline_media"]
        for edge in timeline["edges"]:
            shortcode = edge["node"]["shortcode"]
            
            if edge["node"]["__typename"] == "GraphSidecar":
                response = self._graphql_profile_posts_multi_media(self._profile_username, shortcode)
                for edge in response["edge_sidecar_to_children"]["edges"]:
                    yield Media(edge["node"])

            elif edge["node"]['__typename'] == "GraphVideo":
                edge = self._graphql_profile_posts_multi_media(self._profile_username, shortcode)
                yield Media(edge)

            else:
                yield Media(edge["node"])

        if timeline["page_info"]["has_next_page"]:
            variables = urllib.parse.quote('{"id":"%s","first":%s,"after":"%s"}' % (
                self._profile_id, 12, timeline["page_info"]["end_cursor"]
            ))
            query_url = "%sgraphql/query/?query_hash=%s&variables=%s" % (
                self.IG_HOSTNAME, self.QUERY_HASH_POSTS, variables
            )
            self._timeout()
            response = self._session.get(query_url)
            next_page_results = json.loads(response.content.decode())
            self._profile_metadata = next_page_results["data"]["user"]
            yield from self._graphql_profile_posts()

    def _graphql_profile_posts_multi_media(self, shortcode: str) -> dict:
        """Get a posts multimedia"""
        url = f"{self.IG_HOSTNAME}/p/{shortcode}/?_a=1"
        script_type = fr"window.__additionalDataLoaded\('/{self._profile_username}/p/{shortcode}/',"
        self._timeout()
        metadata = _javascript_parser(self._session.get(url).text, script_type)
        return metadata["graphql"]["shortcode_media"]

    def _timeout(self) -> None:
        """Random timeouts to offset requests."""
        time.sleep(random.randint(420, 720)/100)


class InstaAPI:
    def __init__(self, username, password) -> None:
        self._api: GraphQLAPI = GraphQLAPI(username, password)
        self._api.authenticate()

    def get_profile_followers(self, profile: str):
        """Get all profile followers."""
        self._api._graphql_profile(profile)
        return

    def get_profile_friends(self, profile: str):
        """Get all profile friends."""
        self._api._graphql_profile(profile)
        return
    
    def get_profile_highlight_reels(self, profile: str):
        """Get all profile highlight reels."""
        self._api._graphql_profile(profile)
        return
      
    def get_profile_posts(self, profile: str) -> Generator[Media, None, None]:
        """Get all profile posts."""
        self._api._graphql_profile(profile)
        yield from self._api._graphql_profile_posts()

