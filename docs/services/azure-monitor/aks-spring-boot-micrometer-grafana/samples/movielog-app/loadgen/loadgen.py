"""Synthetic MovieLog users that exercise every movielog.* meter.

Each loop signs up a user, browses movies and reviews on the web and API channels,
posts a review and a comment, and sometimes deletes them. Only the standard library is used.
"""
import http.cookiejar
import json
import os
import random
import string
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("TARGET", "http://movielog")
PAUSE = float(os.environ.get("PAUSE_SECONDS", "1.0"))
MOVIES = [27205, 157336, 155, 496243, 603, 129, 238, 680, 13, 550, 872585, 438631]
POPULAR = MOVIES[:4]


class Session:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def xsrf(self):
        return next((c.value for c in self.jar if c.name == "XSRF-TOKEN"), "")

    def call(self, method, path, form=None, body=None):
        headers = {"X-XSRF-TOKEN": self.xsrf()}
        data = None
        if form is not None:
            data = urllib.parse.urlencode({**form, "_csrf": self.xsrf()}).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
        try:
            with self.opener.open(request, timeout=10) as response:
                raw = response.read()
                return response.status, raw
        except urllib.error.HTTPError as error:
            return error.code, error.read()
        except OSError:
            return 0, b""


def pick_movie():
    return random.choice(POPULAR) if random.random() < 0.6 else random.choice(MOVIES)


def user_journey():
    s = Session()
    name = "lab_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    password = "Lab-" + "".join(random.choices(string.ascii_letters + string.digits, k=12))

    s.call("GET", "/signup")
    s.call("POST", "/signup", form={"username": name, "password": password,
                                    "passwordConfirm": password, "nickname": name[:12]})
    s.call("GET", "/login")
    s.call("POST", "/login", form={"username": name, "password": password})

    for _ in range(random.randint(2, 6)):
        movie = pick_movie()
        channel = "/api/movies/" if random.random() < 0.5 else "/movies/"
        s.call("GET", f"{channel}{movie}")
        time.sleep(PAUSE * random.random())

    status, raw = s.call("GET", "/api/reviews")
    review_ids = []
    if status == 200:
        try:
            review_ids = [item["id"] for item in json.loads(raw).get("items", [])]
        except (ValueError, KeyError, TypeError):
            review_ids = []
    for review_id in random.sample(review_ids, min(len(review_ids), random.randint(1, 3))):
        path = "/api/reviews/" if random.random() < 0.5 else "/reviews/"
        s.call("GET", f"{path}{review_id}")

    if random.random() < 0.7:
        movie = pick_movie()
        rating = random.choices(range(1, 11), weights=[1, 1, 2, 2, 3, 4, 6, 8, 7, 5])[0]
        status, raw = s.call("POST", f"/api/movies/{movie}/reviews",
                             body={"rating": rating, "title": "lab review", "content": "synthetic load"})
        if status == 201:
            review_id = json.loads(raw)["id"]
            if random.random() < 0.6:
                s.call("POST", f"/api/reviews/{review_id}/comments", body={"content": "synthetic comment"})
            if random.random() < 0.1:
                s.call("DELETE", f"/api/reviews/{review_id}")

    if random.random() < 0.2:
        s.call("GET", "/api/movies/search?query=" + urllib.parse.quote("dune"))


def main():
    while True:
        try:
            user_journey()
        except Exception as error:  # keep generating load through transient errors
            print("journey failed:", error, flush=True)
        time.sleep(PAUSE)


if __name__ == "__main__":
    main()
