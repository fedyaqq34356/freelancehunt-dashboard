import os
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.freelancehunt.com/v2"


class FreelancehuntError(Exception):
    def __init__(self, status: int, title: str, detail: str | None = None):
        self.status = status
        self.title = title
        self.detail = detail
        super().__init__(f"{status} {title}: {detail or ''}".strip())


class FreelancehuntClient:
    def __init__(self, token: str | None = None, language: str = "ru"):
        self.token = token or os.getenv("FREELANCEHUNT_TOKEN")
        if not self.token:
            raise RuntimeError("FREELANCEHUNT_TOKEN not set (env or .env)")

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.token}",
                "Accept-Language": language,
            }
        )

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        url = f"{BASE_URL}{path}"
        response = self.session.request(method, url, timeout=30, **kwargs)

        if response.status_code == 429:
            raise FreelancehuntError(429, "Too Many Requests")

        try:
            payload = response.json()
        except ValueError:
            payload = {}

        if not response.ok:
            error = payload.get("error", {})
            raise FreelancehuntError(
                error.get("status", response.status_code),
                error.get("title", "Unknown Error"),
                error.get("detail"),
            )

        return payload

    def get(self, path: str, params: dict | None = None) -> dict[str, Any]:
        return self._request("GET", path, params=params)

    def post(self, path: str, json: dict | None = None) -> dict[str, Any]:
        return self._request("POST", path, json=json)

    # ---- Profile ----
    def my_profile(self) -> dict[str, Any]:
        return self.get("/my/profile")

    def freelancer(self, profile_id: int) -> dict[str, Any]:
        return self.get(f"/freelancers/{profile_id}")

    def employer(self, profile_id: int) -> dict[str, Any]:
        return self.get(f"/employers/{profile_id}")

    def portfolio(self, profile_id: int, page: int = 1) -> dict[str, Any]:
        return self.get(f"/freelancers/{profile_id}/portfolio", params={"page[number]": page})

    def reviews(self, profile_id: int, page: int = 1) -> dict[str, Any]:
        return self.get(f"/freelancers/{profile_id}/reviews", params={"page[number]": page})

    # ---- Projects & bids ----
    def projects(self, page: int = 1, filters: dict | None = None) -> dict[str, Any]:
        params = {"page[number]": page}
        if filters:
            for key, value in filters.items():
                params[f"filter[{key}]"] = value
        return self.get("/projects", params=params)

    def project(self, project_id: int) -> dict[str, Any]:
        return self.get(f"/projects/{project_id}")

    def project_bids(self, project_id: int, status: str | None = None) -> dict[str, Any]:
        params = {"filter[status]": status} if status else None
        return self.get(f"/projects/{project_id}/bids", params=params)

    def my_bids(self, status: str | None = None) -> dict[str, Any]:
        params = {"filter[status]": status} if status else None
        return self.get("/my/bids", params=params)

    def place_bid(
        self,
        project_id: int,
        days: int,
        amount: float,
        currency: str,
        comment: str,
        safe_type: str = "employer",
    ) -> dict[str, Any]:
        payload = {
            "days": days,
            "budget": {"amount": amount, "currency": currency},
            "comment": comment,
            "safe_type": safe_type,
        }
        return self.post(f"/projects/{project_id}/bids", json=payload)

    def revoke_bid(self, project_id: int, bid_id: int) -> dict[str, Any]:
        return self.post(f"/projects/{project_id}/bids/{bid_id}/revoke")

    def restore_bid(self, project_id: int, bid_id: int) -> dict[str, Any]:
        return self.post(f"/projects/{project_id}/bids/{bid_id}/restore")

    # ---- Threads (messaging) ----
    def threads(self, page: int = 1) -> dict[str, Any]:
        return self.get("/threads", params={"page[number]": page})

    def thread_messages(self, thread_id: int, page: int = 1) -> dict[str, Any]:
        return self.get(f"/threads/{thread_id}", params={"page[number]": page})

    def reply_thread(self, thread_id: int, message_html: str) -> dict[str, Any]:
        return self.post(f"/threads/{thread_id}", json={"message_html": message_html})

    def create_thread(self, to_profile_id: int, subject: str, message_html: str) -> dict[str, Any]:
        payload = {
            "to_profile_id": to_profile_id,
            "subject": subject,
            "message_html": message_html,
        }
        return self.post("/threads", json=payload)

    # ---- Feed (notifications) ----
    def feed(self, page: int = 1) -> dict[str, Any]:
        return self.get("/my/feed", params={"page[number]": page})

    def feed_read(self) -> dict[str, Any]:
        return self.post("/my/feed/read")

    # ---- Reference data ----
    def skills(self) -> dict[str, Any]:
        return self.get("/skills")
