# -*- coding: utf-8 -*-
# Copyright 2019 The Matrix.org Foundation C.I.C.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import json

from sygnal.gcmpushkin import GcmPushkin
from tests import testutils
from tests.testutils import DummyResponse

DEVICE_EXAMPLE = {"app_id": "com.example.gcm", "pushkey": "spqr", "pushkey_ts": 42}
DEVICE_EXAMPLE2 = {"app_id": "com.example.gcm", "pushkey": "spqr2", "pushkey_ts": 42}


class TestGcmPushkin(GcmPushkin):
    def __init__(self, name, sygnal, config):
        super().__init__(name, sygnal, config)
        self.preloaded_response = None
        self.preloaded_response_payload = None
        self.last_request_body = None
        self.last_request_headers = None
        self.num_requests = 0

    def preload_with_response(self, code, response_payload):
        """
        Preloads a fake GCM response.
        Args:
            response:

        Returns:

        """
        self.preloaded_response = DummyResponse(code)
        self.preloaded_response_payload = response_payload

    async def _perform_http_request(self, body, headers):
        self.last_request_body = body
        self.last_request_headers = headers
        self.num_requests += 1
        return self.preloaded_response, json.dumps(self.preloaded_response_payload)


class GcmTestCase(testutils.TestCase):
    def config_setup(self, config):
        super(GcmTestCase, self).config_setup(config)
        config["apps"]["com.example.gcm.type"] = "tests.test_gcm.TestGcmPushkin"
        config["apps"]["com.example.gcm.apikey"] = "kii"

    def test_expected(self):
        gcm = self.sygnal.pushkins["com.example.gcm"]
        gcm.preload_with_response(
            200, {"results": [{"message_id": "msg42", "registration_id": "spqr"}]}
        )

        req = self._make_request(self._make_dummy_notification([DEVICE_EXAMPLE]))

        resp = self._collect_request(req)

        self.assertEquals(resp, {"rejected": []})
        self.assertEquals(gcm.num_requests, 1)

    def test_rejected(self):
        gcm = self.sygnal.pushkins["com.example.gcm"]
        gcm.preload_with_response(
            200, {"results": [{"registration_id": "spqr", "error": "NotRegistered"}]}
        )

        req = self._make_request(self._make_dummy_notification([DEVICE_EXAMPLE]))

        resp = self._collect_request(req)

        self.assertEquals(resp, {"rejected": ["spqr"]})
        self.assertEquals(gcm.num_requests, 1)

    def test_regenerated_id(self):
        gcm = self.sygnal.pushkins["com.example.gcm"]
        gcm.preload_with_response(
            200, {"results": [{"registration_id": "spqr_new", "message_id": "msg42"}]}
        )

        req = self._make_request(self._make_dummy_notification([DEVICE_EXAMPLE]))

        resp = self._collect_request(req)

        self.assertEquals(resp, {"rejected": []})

        gcm.preload_with_response(
            200, {"results": [{"registration_id": "spqr_new", "message_id": "msg43"}]}
        )

        req = self._make_request(self._make_dummy_notification([DEVICE_EXAMPLE]))

        resp = self._collect_request(req)

        self.assertEquals(gcm.last_request_body["to"], "spqr_new")

        self.assertEquals(resp, {"rejected": []})
        self.assertEquals(gcm.num_requests, 2)

    def test_batching(self):
        gcm = self.sygnal.pushkins["com.example.gcm"]
        gcm.preload_with_response(
            200,
            {
                "results": [
                    {"registration_id": "spqr", "message_id": "msg42"},
                    {"registration_id": "spqr2", "message_id": "msg42"},
                ]
            },
        )

        req = self._make_request(
            self._make_dummy_notification([DEVICE_EXAMPLE, DEVICE_EXAMPLE2])
        )

        resp = self._collect_request(req)

        self.assertEquals(resp, {"rejected": []})
        self.assertEquals(gcm.last_request_body["registration_ids"], ["spqr", "spqr2"])
        self.assertEquals(gcm.num_requests, 1)

    def test_batching_individual_failure(self):
        gcm = self.sygnal.pushkins["com.example.gcm"]
        gcm.preload_with_response(
            200,
            {
                "results": [
                    {"registration_id": "spqr", "message_id": "msg42"},
                    {"registration_id": "spqr2", "error": "NotRegistered"},
                ]
            },
        )

        req = self._make_request(
            self._make_dummy_notification([DEVICE_EXAMPLE, DEVICE_EXAMPLE2])
        )

        resp = self._collect_request(req)

        self.assertEquals(resp, {"rejected": ["spqr2"]})
        self.assertEquals(gcm.last_request_body["registration_ids"], ["spqr", "spqr2"])
        self.assertEquals(gcm.num_requests, 1)

    def test_regenerated_failure(self):
        gcm = self.sygnal.pushkins["com.example.gcm"]
        gcm.preload_with_response(
            200, {"results": [{"registration_id": "spqr_new", "message_id": "msg42"}]}
        )

        req = self._make_request(self._make_dummy_notification([DEVICE_EXAMPLE]))

        resp = self._collect_request(req)

        self.assertEquals(resp, {"rejected": []})

        # imagine there is some non-negligible time between these two,
        # and the device in question is unregistered

        gcm.preload_with_response(
            200,
            {"results": [{"registration_id": "spqr_new", "error": "NotRegistered"}]},
        )

        req = self._make_request(self._make_dummy_notification([DEVICE_EXAMPLE]))

        resp = self._collect_request(req)

        self.assertEquals(gcm.last_request_body["to"], "spqr_new")

        # the ID translation needs to be transparent as the homeserver will not make sense of it
        # otherwise.
        self.assertEquals(resp, {"rejected": ["spqr"]})
        self.assertEquals(gcm.num_requests, 2)