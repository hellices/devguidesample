"""Synthetic MovieLog users that exercise every movielog.* meter.

Each loop signs up a user and browses movies and reviews on the web and API channels.
It may post a review (70%), comment on it (60% of those), open it and then always delete it,
and search (20%), so a single loop does not touch every meter and synthetic reviews do not pile up.
Half of the loops also run a semantic search and open the AGE graph and similar movies of a hit.
Only the standard library is used.
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
DISCOVER_QUERIES = [
    "꿈속에서 벌어지는 하이스트", "우주에서 가족을 찾아 떠나는 여정", "가난한 가족이 부잣집에 숨어드는 이야기",
    "가상 현실과 인공지능에 맞서는 해커", "마피아 가문의 권력 승계", "아이와 함께 보는 판타지 애니메이션",
    "space opera with rebels and an empire", "a shark terrorizes a beach town", "time travel comedy",
    "전쟁 속 생존과 우정", "슈퍼히어로 팀이 지구를 지키는 영화", "복수를 위해 살아가는 남자",
]


class Session:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.last_url = ""

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
                # Redirects are followed, so this is where the request finally landed.
                self.last_url = response.geturl()
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
    status, _ = s.call("POST", "/signup", form={"username": name, "password": password,
                                                "passwordConfirm": password, "nickname": name[:12]})
    # Success redirects to /login?registered; a failed signup re-renders the form with 200.
    if status != 200 or "registered" not in s.last_url:
        raise RuntimeError(f"signup failed (status {status})")
    s.call("GET", "/login")
    status, _ = s.call("POST", "/login", form={"username": name, "password": password})
    # Success redirects to /reviews; a failed login lands on /login?error, also with 200.
    if status != 200 or "/login" in s.last_url:
        raise RuntimeError(f"login failed (status {status})")

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
            s.call("GET", f"/reviews/{review_id}")
            # Synthetic reviews are always removed so they do not bury real reviews in the list.
            s.call("DELETE", f"/api/reviews/{review_id}")

    if random.random() < 0.2:
        s.call("GET", "/api/movies/search?q=" + urllib.parse.quote("dune"))

    if random.random() < 0.5:
        discover(s)


def discover(s):
    query = random.choice(DISCOVER_QUERIES)
    if random.random() < 0.5:
        s.call("GET", "/discover?q=" + urllib.parse.quote(query))
    status, raw = s.call("GET", "/api/discover/search?limit=8&q=" + urllib.parse.quote(query))
    if status != 200:
        return
    try:
        ids = [hit["tmdbId"] for hit in json.loads(raw)]
    except (ValueError, KeyError, TypeError):
        return
    if not ids:
        return
    s.call("GET", "/api/discover/graph?ids=" + ",".join(str(i) for i in ids))
    movie = random.choice(ids)
    s.call("GET", f"/api/discover/graph/movies/{movie}")
    s.call("GET", f"/api/discover/movies/{movie}/similar")
    s.call("GET", f"/movies/{movie}")


def main():
    while True:
        try:
            user_journey()
        except Exception as error:  # keep generating load through transient errors
            print("journey failed:", error, flush=True)
        time.sleep(PAUSE)


if __name__ == "__main__":
    main()
