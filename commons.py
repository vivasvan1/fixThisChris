# Common function for sending GitHub API requests
import logging
import requests

import os

from env import GITHUB_ACCESS_TOKEN


def send_github_request(url: str, method: str, headers: dict[str, str] | None = None):
    if headers is None:
        headers = {
            "Authorization": f"Bearer {GITHUB_ACCESS_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
        }
    response = requests.request(method, url, headers=headers)
    if response.status_code in [200, 204, 205]:
        return response
    else:
        print(f"Failed to {method} {url} | Status Code: {response.status_code}")
        return None
