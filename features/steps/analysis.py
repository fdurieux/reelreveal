from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from behave import given, then, when

from reelreveal.cli import parser
from reelreveal.core import ReelRevealError, analyze, download


@given("the CLI defaults")
def defaults(context):
    context.args = parser().parse_args([])


@given('the CLI target is "{target}"')
def target(context, target):
    context.args = parser().parse_args(["--identify", target])


@then('the identification target is "{target}"')
def check_target(context, target):
    assert context.args.identify == target


@given("Instagram retrieval is unavailable")
def unavailable(context):
    context.error = None


@when("a Reel is downloaded")
def attempt(context):
    with (
        TemporaryDirectory() as directory,
        patch("reelreveal.core.run", side_effect=ReelRevealError("Unavailable")),
    ):
        try:
            download("https://www.instagram.com/reel/example/", Path(directory))
        except ReelRevealError as error:
            context.error = str(error)


@then("the error suggests a local video")
def recovery(context):
    assert "--video FILE" in context.error


@given("a sampled frame without a vision provider")
def frame(context):
    context.frames = [{"path": "frame.jpg", "timestamp_seconds": 1.0}]


@when("the frame is analyzed")
def analyze_frame(context):
    context.results = analyze(context.frames, "records", None)


@then("no identifications are reported")
def no_claim(context):
    assert context.results[0]["items"] == []
