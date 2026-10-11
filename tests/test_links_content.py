import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import quote

from douyin_downloader.adapters.douyin.content import (
    decode_page_data,
    find_aweme,
    parse_content,
    quality_list,
    urls_from,
)
from douyin_downloader.adapters.douyin.links import extract_url, parse_url, resolve_link
from douyin_downloader.adapters.transfer import safe_name
from douyin_downloader.domain.models import DownloadError


class LinkTests(unittest.TestCase):
    def test_share_text_and_punctuation(self):
        self.assertEqual(
            extract_url("复制 https://v.douyin.com/Ab_c-12/ ，打开看看"),
            "https://v.douyin.com/Ab_c-12/",
        )
        self.assertIsNone(extract_url("https://www.douyin.com.evil.example/video/123"))
        self.assertIsNone(extract_url("python douyin_download.py"))

    def test_video_note_and_query_formats(self):
        cases = [
            ("https://www.douyin.com/video/123", "123", "video"),
            ("https://www.douyin.com/note/456?from=share", "456", "note"),
            ("https://www.iesdouyin.com/share/note/456/", "456", "note"),
            ("https://www.iesdouyin.com/share/video/789/", "789", "video"),
            ("https://www.douyin.com/?modal_id=789", "789", "video"),
        ]
        for url, identity, kind in cases:
            with self.subTest(url=url):
                parsed = parse_url(url)
                self.assertEqual((parsed.aweme_id, parsed.kind), (identity, kind))

    def test_short_link_redirect_to_note(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.url = "https://www.douyin.com/note/456"
        with patch("douyin_downloader.adapters.douyin.links.requests.get", return_value=response):
            self.assertEqual(resolve_link("https://v.douyin.com/test/").kind, "note")

    def test_invalid_input_is_explicit_error(self):
        with self.assertRaises(DownloadError):
            resolve_link("not a link")

    def test_windows_filename_preserves_letters_and_spaces(self):
        self.assertEqual(safe_name("A TEST? normal: title"), "A TEST normal title")
        self.assertEqual(safe_name("CON"), "_CON")
        self.assertEqual(safe_name("text. "), "text")


class ContentTests(unittest.TestCase):
    def test_all_declared_dynamic_candidates_are_available_for_fallback(self):
        content = parse_content(
            {
                "images": [
                    {
                        "url_list": ["https://images.example/still.jpg"],
                        "video": {
                            "play_addr": [{"src": "https://v.douyinvod.com/primary.mp4"}],
                            "bit_rate_list": [
                                {
                                    "gear_name": "720",
                                    "bit_rate": 200,
                                    "play_addr": [{"src": "https://v.douyinvod.com/bitrate.mp4"}],
                                }
                            ],
                            "play_addr_h264": [{"src": "https://v.douyinvod.com/h264.mp4"}],
                            "play_addr_h265": [{"src": "https://v.douyinvod.com/h265.mp4"}],
                            "play_addr_lowbr": [{"src": "https://v.douyinvod.com/low.mp4"}],
                        },
                    }
                ]
            },
            "123",
        )
        self.assertEqual(len(content.image_videos[0]), 5)
        self.assertIn("https://v.douyinvod.com/h265.mp4", content.image_videos[0])

    def test_src_object_addresses_preserve_dynamic_video(self):
        address = "https://v.douyinvod.com/motion.mp4"
        content = parse_content(
            {
                "images": [
                    {
                        "urlList": ["https://images.example/still.webp"],
                        "livePhotoType": 1,
                        "video": {"duration": 4067, "playAddr": [{"src": address}]},
                    }
                ],
            },
            "456",
        )
        self.assertEqual(content.image_videos, {0: (address,)})
        self.assertEqual(urls_from({"src": address}), (address,))
        self.assertEqual(urls_from([{"src": address}, {"src": address}, None]), (address,))

    def test_dynamic_video_does_not_depend_on_duration_metadata(self):
        address = "https://v.douyinvod.com/motion.mp4"
        content = parse_content(
            {
                "images": [
                    {
                        "url_list": ["https://images.example/still.jpg"],
                        "video": {"duration": 0, "play_addr": [{"src": address}]},
                    }
                ]
            },
            "456",
        )
        self.assertEqual(content.image_videos, {0: (address,)})

    def test_dynamic_photo_with_only_watermarked_video_fails(self):
        with self.assertRaisesRegex(DownloadError, "Dynamic photo"):
            parse_content(
                {
                    "images": [
                        {
                            "url_list": ["https://images.example/still.jpg"],
                            "live_photo_type": 1,
                            "video": {
                                "play_addr": [
                                    {"src": "https://v.douyinvod.com/motion.mp4?watermark=1"}
                                ]
                            },
                        }
                    ]
                },
                "456",
            )

    def test_photo_uses_clean_preview_and_rejects_watermark_fallback(self):
        original = "https://images.example/source~tplv-dy-aweme-images:q75.webp"
        watermarked = "https://images.example/source~tplv-dy-water-v2:fake.webp"
        content = parse_content(
            {"images": [{"url_list": [original], "download_url_list": [watermarked]}]}, "123"
        )
        self.assertEqual(content.images, [(original,)])
        with self.assertRaisesRegex(DownloadError, "watermark-free"):
            parse_content({"images": [{"download_url_list": [watermarked]}]}, "123")

    def test_flight_camelcase_photo_with_music(self):
        detail = {
            "awemeId": "456",
            "desc": "sample",
            "authorInfo": {"nickname": "author"},
            "images": [{"urlList": ["https://images.example/a.webp"]}],
            "music": {"duration": 12, "playUrl": {"urlList": ["https://music.example/a.mp3"]}},
        }
        props = {"awemeId": "456", "aweme": {"detail": detail}}
        chunks = [[1, "7:" + json.dumps(["$", "$L1", None, props]) + "\n"], [1, "3:I{}\n"], [0]]
        decoded = decode_page_data(None, chunks)
        content = parse_content(find_aweme(decoded, "456"), "456")
        self.assertEqual(content.kind, "note")
        self.assertEqual(content.author, "author")
        self.assertEqual(len(content.images), 1)
        self.assertEqual(content.music_duration, 12)
        self.assertEqual(content.music_urls, ("https://music.example/a.mp3",))

    def test_render_data_and_target_identity(self):
        data = {
            "recommendations": [{"aweme_id": "999", "video": {"duration": 1}}],
            "aweme_detail": {"aweme_id": "123", "video": {"duration": 2}},
        }
        decoded = decode_page_data(quote(json.dumps(data)), [])
        self.assertEqual(find_aweme(decoded, "123")["aweme_id"], "123")
        self.assertIsNone(find_aweme(decoded, "555"))

    def test_quality_sort_and_fallback_without_bitrate(self):
        video = {
            "bit_rate": [
                {
                    "gear_name": "hdr_1080",
                    "bit_rate": 500,
                    "play_addr": {"url_list": ["https://v.douyinvod.com/h.mp4"]},
                },
                {
                    "gear_name": "normal_720",
                    "bit_rate": 200,
                    "play_addr": {"url_list": ["https://v.douyinvod.com/a.mp4"]},
                },
            ]
        }
        self.assertEqual(quality_list(video)[0].name, "normal_720")
        fallback = quality_list(
            {"play_addr": {"url_list": ["https://v.douyinvod.com/original.mp4"]}}
        )
        self.assertEqual(fallback[0].name, "original")
        self.assertEqual(
            quality_list(
                {"play_addr": {"url_list": ["https://v.douyinvod.com/a.mp4?watermark=1"]}}
            ),
            [],
        )

    def test_missing_photo_address_is_error(self):
        with self.assertRaises(DownloadError):
            parse_content({"images": [{}]}, "456")
