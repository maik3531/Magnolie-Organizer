"""Synthetic transport tests: no credentials, sockets or GitLab mutations."""

from email.message import Message
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPSHandler, build_opener
from urllib.response import addinfourl

import gitlab_storage_api as api_module
from gitlab_storage_api import GitLabAPI, GitLabAPIError


COMMIT = "a" * 40
TOKEN = "synthetic-token-never-print"


class Response(io.BytesIO):
    def __init__(self, value=None, *, body=None, status=200, headers=None):
        super().__init__(json.dumps(value).encode() if body is None else body)
        self.status = status
        self.headers = Message()
        for name, value in (headers or {}).items():
            self.headers[name] = value
        self.url = None
        self.read_sizes = []

    def geturl(self):
        return self.url

    def read(self, size=-1):
        self.read_sizes.append(size)
        if size < 0:
            raise AssertionError("A response must never be read without a bound")
        return super().read(size)


class FakeOpener:
    def __init__(self, handler):
        self.handler = handler
        self.requests = []

    def open(self, request, *, timeout):
        self.requests.append(request)
        assert timeout == api_module.TIMEOUT
        response = self.handler(request)
        if response.url is None:
            response.url = request.full_url
        return response


def package(identifier, name="release", status="default"):
    return {"id": identifier, "name": name, "version": "1.0.%d" % identifier,
            "package_type": "generic", "status": status}


def expected(data):
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


class StorageAPITests(unittest.TestCase):
    def client(self, handler):
        client = GitLabAPI("maik3531/mint-forgs", token=TOKEN)
        client._opener = FakeOpener(handler)
        return client

    def test_all_statuses_and_more_than_one_hundred_packages_without_headers(self):
        def handler(request):
            query = parse_qs(urlsplit(request.full_url).query)
            self.assertEqual(query["per_page"], ["100"])
            self.assertEqual(query["include_versionless"], ["true"])
            page = int(query["page"][0])
            status = query["status"][0]
            if status == "default":
                rows = [package(index) for index in range(1, 206)]
                rows.append(package(900, name="release-extra"))
                return Response(rows[(page - 1) * 100:page * 100])
            return Response([package(1000 + api_module.PACKAGE_STATUSES.index(status), status=status)])
        client = self.client(handler)
        rows = client.packages("release")
        self.assertEqual(len(rows), 210)
        self.assertNotIn(900, [row["id"] for row in rows])
        self.assertEqual({row["status"] for row in rows}, set(api_module.PACKAGE_STATUSES))
        self.assertEqual(len(client._opener.requests), 8)

    def test_identical_ids_across_status_queries_are_deduplicated(self):
        client = self.client(lambda _: Response([package(1)]))
        self.assertEqual(client.packages("release"), [package(1)])

    def test_conflicting_ids_across_status_queries_fail(self):
        def handler(request):
            status = parse_qs(urlsplit(request.full_url).query)["status"][0]
            return Response([package(1, status=status)])
        with self.assertRaisesRegex(GitLabAPIError, "changed during inventory"):
            self.client(handler).packages("release")

    def test_file_pagination_reads_extra_empty_page_after_full_page(self):
        def handler(request):
            page = int(parse_qs(urlsplit(request.full_url).query)["page"][0])
            return Response([{"id": index} for index in range(1, 101)] if page == 1 else [],
                            headers={"X-Page": str(page), "X-Next-Page": ""})
        client = self.client(handler)
        self.assertEqual(len(client.files(7)), 100)
        self.assertEqual(len(client._opener.requests), 2)

    def test_repeated_page_is_rejected(self):
        client = self.client(lambda _: Response([{"id": index} for index in range(1, 101)]))
        with self.assertRaisesRegex(GitLabAPIError, "Repeated object/page"):
            client.files(7)
        self.assertEqual(len(client._opener.requests), 2)

    def test_bad_next_page_or_wrong_current_page_is_rejected(self):
        for headers in ({"X-Next-Page": "1"}, {"X-Next-Page": "3"},
                        {"X-Next-Page": "https://elsewhere.invalid"}, {"X-Page": "2"},
                        {"X-Per-Page": "20"}, {"X-Next-Page": "2"}):
            with self.subTest(headers=headers), self.assertRaises(GitLabAPIError):
                self.client(lambda _: Response([], headers=headers)).files(1)

    def test_page_limit_does_not_return_partial_inventory(self):
        def handler(request):
            page = int(parse_qs(urlsplit(request.full_url).query)["page"][0])
            return Response([{"id": page * 100 + index} for index in range(100)])
        with patch.object(api_module, "MAX_PAGES", 2), self.assertRaisesRegex(GitLabAPIError, "Pagination limit"):
            self.client(handler).files(7)

    def test_inconsistent_totals_do_not_allow_a_partial_inventory(self):
        for headers in ({"X-Total": "101"}, {"X-Total-Pages": "2"}, {"X-Total": "unknown"}):
            with self.subTest(headers=headers), self.assertRaises(GitLabAPIError):
                self.client(lambda _: Response([{"id": 1}], headers=headers)).files(7)

    def test_malformed_package_identity_is_not_silently_omitted(self):
        with self.assertRaisesRegex(GitLabAPIError, "Incomplete package identity"):
            self.client(lambda _: Response([{"id": 1}])).packages("release")

    def test_invalid_ids_and_malformed_pages_fail(self):
        for value in ([{"id": True}], [{"id": "7"}], [{"id": 0}], [{"id": -1}],
                      [{"id": 1}, {"id": 1}], [{"missing": 1}], {"error": "body"}):
            with self.subTest(value=value), self.assertRaises(GitLabAPIError):
                self.client(lambda _: Response(value)).files(7)

    def test_missing_objects_are_only_404_not_403_or_500(self):
        for operation in (lambda client: client.file("metadata.json", "main"),
                          lambda client: client.package(1)):
            for status in (404, 403, 500):
                def handler(request):
                    raise HTTPError(request.full_url, status, TOKEN, {}, io.BytesIO(TOKEN.encode()))
                client = self.client(handler)
                if status == 404:
                    self.assertIsNone(operation(client))
                else:
                    with self.assertRaises(GitLabAPIError) as caught:
                        operation(client)
                    self.assertEqual(caught.exception.status, status)
                    self.assertNotIn(TOKEN, str(caught.exception))

    def test_delete_requires_204_and_does_not_swallow_404(self):
        client = self.client(lambda _: Response(body=b"", status=204))
        self.assertIsNone(client.delete_package(17))
        self.assertEqual(client._opener.requests[0].method, "DELETE")
        for status in (200, 202, 404):
            with self.subTest(status=status), self.assertRaises(GitLabAPIError) as caught:
                self.client(lambda _: Response(body=b"", status=status)).delete_package(17)
            self.assertEqual(caught.exception.status, status)

    def test_redirects_do_not_forward_credentials_to_any_target(self):
        for status in (301, 302, 303, 307, 308):
            requests = []
            class StubHTTPS(HTTPSHandler):
                def https_open(self, request):
                    requests.append(request)
                    headers = Message()
                    headers["Location"] = "https://elsewhere.invalid/" + TOKEN
                    result = addinfourl(io.BytesIO(TOKEN.encode()), headers, request.full_url, status)
                    result.msg = "Synthetic redirect"
                    return result
            client = GitLabAPI("maik3531/mint-forgs", token=TOKEN)
            client._opener = build_opener(StubHTTPS(), api_module._RejectRedirects())
            with self.subTest(status=status), self.assertRaises(GitLabAPIError) as caught:
                client.head("main")
            self.assertEqual(caught.exception.status, status)
            self.assertNotIn(TOKEN, str(caught.exception))
            self.assertEqual(len(requests), 1)
            self.assertEqual(urlsplit(requests[0].full_url).netloc, "gitlab.com")

    def test_transport_errors_are_sanitized(self):
        def handler(_):
            raise URLError("url/" + TOKEN)
        with self.assertRaises(GitLabAPIError) as caught:
            self.client(handler).project()
        self.assertNotIn(TOKEN, str(caught.exception))

    def test_project_statistics_are_not_fabricated(self):
        result = {"id": 78301901, "path_with_namespace": "maik3531/mint-forgs",
                  "statistics": {"repository_size": 100, "lfs_objects_size": 7}}
        client = self.client(lambda _: Response(result))
        self.assertEqual(client.project(), result)
        self.assertEqual(parse_qs(urlsplit(client._opener.requests[0].full_url).query), {"statistics": ["true"]})
        for invalid in ({"id": 1, "path_with_namespace": "maik3531/mint-forgs"},
                        dict(result, path_with_namespace="another/project")):
            with self.assertRaises(GitLabAPIError):
                self.client(lambda _: Response(invalid)).project()

    def test_encoded_segments_queries_and_commit_payload(self):
        client = self.client(lambda _: Response({"commit": {"id": COMMIT}}))
        self.assertEqual(client.head("release/ready"), COMMIT)
        self.assertIn("/projects/maik3531%2Fmint-forgs/repository/branches/release%2Fready",
                      client._opener.requests[0].full_url)
        path = "metadata/release #1.json"
        client = self.client(lambda _: Response({"file_path": path}))
        self.assertEqual(client.file(path, "branch/+name"), {"file_path": path})
        request = client._opener.requests[0]
        self.assertIn("metadata%2Frelease%20%231.json?", request.full_url)
        self.assertEqual(parse_qs(urlsplit(request.full_url).query), {"ref": ["branch/+name"]})
        actions = [{"action": "update", "file_path": "current.json", "content": "{}",
                    "last_commit_id": COMMIT}]
        client = self.client(lambda _: Response({"id": COMMIT}, status=201))
        self.assertEqual(client.commit("main", actions, "Refs #698\nStorage activation"), COMMIT)
        request = client._opener.requests[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(json.loads(request.data), {
            "branch": "main", "actions": actions, "commit_message": "Refs #698\nStorage activation"})

    def test_json_limit_duplicate_keys_and_truncation(self):
        for body, headers in ((b"x" * 130, {}), (b"{}", {"Content-Length": "12"}),
                              (b'{"id":1,"id":2}', {}), (b'{"id":NaN}', {}),
                              (b"{broken}", {}), (b"{}", {"Content-Encoding": "gzip"})):
            with self.subTest(body=body), patch.object(api_module, "JSON_LIMIT", 128), self.assertRaises(GitLabAPIError):
                self.client(lambda _: Response(body=body, headers=headers)).project()

    def test_download_checks_hash_size_truncation_and_oversize_streaming(self):
        data = b"package" * 20000
        response = Response(body=data, headers={"Content-Length": str(len(data))})
        self.client(lambda _: response).verify_download("release", "1.0.1", "package.bin", expected(data))
        self.assertTrue(response.read_sizes)
        self.assertLessEqual(max(response.read_sizes), api_module.BLOCK_BYTES)
        for body, headers in ((data[:-1], {}), (data + b"x", {}), (b"x" * len(data), {}),
                              (data, {"Content-Length": str(len(data) - 1)})):
            with self.subTest(size=len(body), headers=headers), self.assertRaises(GitLabAPIError):
                self.client(lambda _: Response(body=body, headers=headers)).verify_download(
                    "release", "1.0.1", "package.bin", expected(data))

    def test_public_download_omits_publisher_token_but_inventory_keeps_it(self):
        data = b"public release"
        def handler(request):
            if "/packages/generic/" in request.full_url:
                self.assertIsNone(request.get_header("Private-token"))
                self.assertIsNone(request.get_header("Authorization"))
                return Response(body=data)
            self.assertEqual(request.get_header("Private-token"), TOKEN)
            return Response([])
        client = self.client(handler)
        client.verify_download("release", "1.0.1", "package.bin", expected(data))
        self.assertEqual(client.files(7), [])
        self.assertEqual(len(client._opener.requests), 2)

    def test_private_registry_does_not_pass_public_download_verification(self):
        def handler(request):
            # The fake endpoint would permit a credentialed publisher, just as a
            # real private registry does. Anonymous clients must remain blocked.
            if request.get_header("Private-token") == TOKEN:
                return Response(body=b"private release")
            raise HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO())
        client = self.client(handler)
        with self.assertRaises(GitLabAPIError) as caught:
            client.verify_download("release", "1.0.1", "package.bin", expected(b"private release"))
        self.assertEqual(caught.exception.status, 403)
        self.assertIsNone(client._opener.requests[0].get_header("Private-token"))

    def test_upload_uses_bounded_file_stream_and_content_length(self):
        data = b"artifact" * 40000
        chunks = []
        def handler(request):
            self.assertEqual(request.method, "PUT")
            self.assertEqual(request.get_header("Content-length"), str(len(data)))
            self.assertFalse(isinstance(request.data, (bytes, bytearray)))
            while block := request.data.read(8192):
                self.assertLessEqual(len(block), 8192)
                chunks.append(block)
            return Response({"message": "201 Created"}, status=201)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "artifact.bin"
            path.write_bytes(data)
            self.client(handler).upload("release", "1.0.1", "artifact.bin", path)
        self.assertEqual(b"".join(chunks), data)

    def test_upload_rejects_changes_or_unconsumed_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "artifact.bin"
            path.write_bytes(b"before")
            with self.assertRaisesRegex(GitLabAPIError, "not fully sent"):
                self.client(lambda _: Response({}, status=201)).upload("release", "1", "a.bin", path)
            def handler(request):
                while request.data.read(8192):
                    pass
                path.write_bytes(b"changed")
                return Response({}, status=201)
            with self.assertRaisesRegex(GitLabAPIError, "changed while sending"):
                self.client(handler).upload("release", "1", "a.bin", path)

    def test_invalid_project_or_path_rejected_before_request(self):
        for project in ("https://gitlab.com/maik3531/mint-forgs", "other/mint-forgs", "maik3531/../x",
                        "maik3531/x?token=secret", "maik3531/x@y", "maik3531/x\n"):
            with self.subTest(project=project), self.assertRaises(GitLabAPIError):
                GitLabAPI(project, token=TOKEN)
        client = self.client(lambda _: self.fail("invalid input attempted a network request"))
        for path in ("/absolute", "../escape", "nested/../escape", "a\\b", "a\n"):
            with self.subTest(path=path), self.assertRaises(GitLabAPIError):
                client.file(path, "main")
        with self.assertRaises(GitLabAPIError):
            client.verify_download("release", "1", "../escape", expected(b"x"))
        for identifier in (True, -1, 0, "1"):
            with self.assertRaises(GitLabAPIError):
                client.delete_package(identifier)


if __name__ == "__main__":
    unittest.main()
