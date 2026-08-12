"""A failed request carries the gateway's own id for it.

The gateway logs every request it serves against an id and returns that id in
a response header. Nothing read it back, so a customer reporting a failure gave
support a rough time and a description, and matching that to a row meant
grepping a day of traffic for a request nobody could name.

The id is orthogonal to what went wrong, which is why it is appended once
around the summary rather than at each of that function's per-error-shape
returns.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx

from agent.ninegate_leash import REQUEST_ID_HEADER, request_id_from_error
from run_agent import AIAgent

REQUEST_ID = "0f8fad5b-d9cb-469f-a165-70867728950e"


def _error_with_headers(headers, *, status_code: int = 500, message: str = "boom") -> Exception:
    err = Exception(message)
    err.status_code = status_code
    err.response = SimpleNamespace(headers=headers, text="")
    return err


class TestExtraction:
    def test_reads_the_header_off_the_response(self) -> None:
        err = _error_with_headers(httpx.Headers({REQUEST_ID_HEADER: REQUEST_ID}))

        assert request_id_from_error(err) == REQUEST_ID

    def test_finds_it_through_the_cause_chain(self) -> None:
        """SDKs re-raise; the response is usually on the wrapped exception."""
        inner = _error_with_headers(httpx.Headers({REQUEST_ID_HEADER: REQUEST_ID}))
        outer = RuntimeError("request failed")
        outer.__cause__ = inner

        assert request_id_from_error(outer) == REQUEST_ID

    def test_a_plain_dict_that_does_not_fold_case_still_answers(self) -> None:
        err = _error_with_headers({"X-NineGate-Request-Id": REQUEST_ID})

        assert request_id_from_error(err) == REQUEST_ID

    def test_absent_header_is_none(self) -> None:
        """An unlocked build talking to another provider never sees one."""
        err = _error_with_headers(httpx.Headers({"content-type": "application/json"}))

        assert request_id_from_error(err) is None

    def test_no_response_at_all_is_none(self) -> None:
        assert request_id_from_error(RuntimeError("connection reset")) is None

    def test_an_absurd_value_is_capped(self) -> None:
        """The value is read off the wire and then shown to a person."""
        err = _error_with_headers({REQUEST_ID_HEADER: "x" * 5000})

        extracted = request_id_from_error(err)

        assert extracted is not None
        assert len(extracted) <= 64

    def test_control_characters_are_stripped(self) -> None:
        err = _error_with_headers({REQUEST_ID_HEADER: f"  {REQUEST_ID}\n  "})

        assert request_id_from_error(err) == REQUEST_ID


class TestItReachesTheMessage:
    def test_the_summary_names_the_request(self) -> None:
        err = _error_with_headers(httpx.Headers({REQUEST_ID_HEADER: REQUEST_ID}))

        summary = AIAgent._summarize_api_error(err)

        assert REQUEST_ID in summary, "the id never reached the message a human reads"

    def test_the_original_detail_survives(self) -> None:
        """Appending the id must not cost the error message itself."""
        err = Exception("")
        err.status_code = 400
        err.body = {"error": {"message": "model `foo` does not exist"}}
        err.response = SimpleNamespace(
            headers=httpx.Headers({REQUEST_ID_HEADER: REQUEST_ID}), text=""
        )

        summary = AIAgent._summarize_api_error(err)

        assert "model `foo` does not exist" in summary
        assert "HTTP 400" in summary
        assert REQUEST_ID in summary

    def test_nothing_is_appended_when_there_is_no_id(self) -> None:
        err = Exception("")
        err.status_code = 400
        err.body = {"error": {"message": "model `foo` does not exist"}}
        err.response = SimpleNamespace(headers=httpx.Headers({}), text="")

        summary = AIAgent._summarize_api_error(err)

        assert "NineGate request" not in summary
        assert "model `foo` does not exist" in summary
