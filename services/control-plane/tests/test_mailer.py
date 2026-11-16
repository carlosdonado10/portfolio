import json

import httpx
from control_plane.mailer import NullMailer, ResendMailer


async def test_resend_mailer_posts_expected_request():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "1"})

    mailer = ResendMailer("key123", "Lab <lab@x.dev>", transport=httpx.MockTransport(handler))
    await mailer.send("v@x.co", "Subj", "Body")
    assert seen["url"] == "https://api.resend.com/emails"
    assert seen["auth"] == "Bearer key123"
    assert seen["body"] == {
        "from": "Lab <lab@x.dev>",
        "to": ["v@x.co"],
        "subject": "Subj",
        "text": "Body",
    }


async def test_resend_mailer_raises_on_error_status():
    mailer = ResendMailer(
        "k", "a@b.c", transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    try:
        await mailer.send("v@x.co", "s", "b")
    except httpx.HTTPStatusError:
        return
    raise AssertionError("expected HTTPStatusError")


async def test_null_mailer_does_not_raise():
    await NullMailer().send("v@x.co", "s", "b")
