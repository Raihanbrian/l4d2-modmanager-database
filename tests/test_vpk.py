import io
import struct
import unittest

from l4d2_mod_db.vpk import ParserLimits, VpkError, canonicalize_virtual_path, parse_vpk
from .vpk_fixtures import FixtureEntry, build_vpk


class VpkParserTests(unittest.TestCase):
    def parse(self, data, limits=ParserLimits()):
        return parse_vpk(io.BytesIO(data), len(data), limits)

    def assert_error(self, data, code, limits=ParserLimits()):
        with self.assertRaises(VpkError) as caught:
            self.parse(data, limits)
        self.assertEqual(caught.exception.code, code)

    def test_versions_one_and_two_list_paths_without_reading_asset_payloads(self):
        for version in (1, 2):
            with self.subTest(version=version):
                data = build_vpk(("Materials/Test.VMT", "models/a.mdl", "addoninfo.txt"), version=version)
                stream = io.BytesIO(data)
                result = parse_vpk(stream, len(data))
                self.assertEqual(result.version, version)
                self.assertEqual([asset.canonical_path for asset in result.assets], ["addoninfo.txt", "materials/test.vmt", "models/a.mdl"])
                self.assertEqual(result.assets[1].original_path, "Materials/Test.VMT")
                self.assertEqual(stream.tell(), result.bytes_read)
                self.assertLess(result.bytes_read, len(data))
                self.assertEqual(len(result.index_sha256), 64)

    def test_preload_and_extensionless_root_entries(self):
        data = build_vpk(entries=[FixtureEntry(" ", " ", "LICENSE", b"PRELOAD", b"body")])
        result = self.parse(data)
        asset = result.assets[0]
        self.assertEqual(asset.original_path, "LICENSE")
        self.assertEqual(asset.preload_bytes, 7)
        self.assertEqual(asset.size_bytes, 11)

    def test_empty_tree_is_supported(self):
        self.assertFalse(self.parse(build_vpk(())).assets)

    def test_external_archive_references_are_metadata_only(self):
        result = self.parse(build_vpk(entries=[FixtureEntry(archive=2, offset=123456)]))
        self.assertEqual(result.external_archives, (2,))
        self.assertEqual(result.assets[0].archive_offset, 123456)

    def test_backslashes_case_and_utf8_are_preserved_and_canonicalized(self):
        result = self.parse(build_vpk(entries=[FixtureEntry("VMT", "Materials\\Éxample", "Mixed")]))
        self.assertEqual(result.assets[0].original_path, "Materials\\Éxample/Mixed.VMT")
        self.assertEqual(result.assets[0].canonical_path, "materials/éxample/mixed.vmt")

    def test_index_fingerprint_is_deterministic_and_is_not_a_payload_hash(self):
        data = build_vpk()
        self.assertEqual(self.parse(data).index_sha256, self.parse(data).index_sha256)
        # Changing payload alone without adjusting directory CRC does not change
        # the directory fingerprint; payload integrity is deliberately unverified.
        altered = data[:-1] + bytes([data[-1] ^ 1])
        self.assertEqual(self.parse(data).index_sha256, self.parse(altered).index_sha256)

    def test_invalid_magic_version_and_short_headers(self):
        self.assert_error(b"short", "TRUNCATED_VPK")
        self.assert_error(b"x" * 12, "INVALID_MAGIC")
        self.assert_error(build_vpk(version=3), "UNSUPPORTED_VERSION")

    def test_declared_tree_must_fit_file_and_budget(self):
        self.assert_error(struct.pack("<III", 0x55AA1234, 1, 999), "TRUNCATED_VPK")
        self.assert_error(struct.pack("<III", 0x55AA1234, 1, 0), "TREE_LIMIT")
        self.assert_error(build_vpk(), "TREE_LIMIT", ParserLimits(max_tree_bytes=1))

    def test_v2_section_bounds(self):
        data = bytearray(build_vpk(version=2))
        struct.pack_into("<I", data, 12, 0xFFFFFFFF)
        self.assert_error(bytes(data), "INVALID_SECTIONS")

    def test_declared_stream_length_does_not_hide_actual_truncation(self):
        with self.assertRaises(VpkError) as caught:
            parse_vpk(io.BytesIO(build_vpk()[:15]), 9999)
        self.assertEqual(caught.exception.code, "TRUNCATED_VPK")

    def test_bad_terminator_and_embedded_offsets(self):
        self.assert_error(build_vpk(entries=[FixtureEntry(terminator=0)]), "INVALID_TERMINATOR")
        self.assert_error(build_vpk(entries=[FixtureEntry(offset=999999)]), "INVALID_OFFSET")

    def test_unknown_archive_number_is_rejected(self):
        self.assert_error(build_vpk(entries=[FixtureEntry(archive=0xFFFF)]), "INVALID_ARCHIVE")

    def test_duplicate_and_case_colliding_asset_paths_are_rejected(self):
        for paths in (("scripts/a.txt", "scripts/a.txt"), ("Scripts/A.TXT", "scripts/a.txt")):
            with self.subTest(paths=paths):
                self.assert_error(build_vpk(paths), "DUPLICATE_ASSET")

    def test_entry_and_path_limits(self):
        self.assert_error(build_vpk(("scripts/a.txt", "scripts/b.txt")), "ENTRY_LIMIT", ParserLimits(max_entries=1))
        self.assert_error(build_vpk(), "INVALID_TREE_STRING", ParserLimits(max_path_bytes=2))
        with self.assertRaises(VpkError):
            canonicalize_virtual_path("a/long.txt", max_bytes=3)

    def test_unsafe_virtual_directories_basenames_and_extensions(self):
        for entry in (FixtureEntry(directory="../outside"), FixtureEntry(directory="C:\\outside"),
                      FixtureEntry(directory="/outside"), FixtureEntry(directory="a//b"),
                      FixtureEntry(basename="../escape"), FixtureEntry(extension="../txt"),
                      FixtureEntry(directory="folder\\..\\escape"), FixtureEntry(basename="bad:stream")):
            with self.subTest(entry=entry):
                self.assert_error(build_vpk(entries=[entry]), "UNSAFE_ASSET_PATH")

    def test_virtual_path_normalization_never_collapses_traversal(self):
        for path in ("", "/a.txt", "\\a.txt", "C:a.txt", "a/../b.txt", "a/./b.txt", "a//b.txt", "a.txt:stream",
                     "a\x00.txt", "a\n.txt", "a./b.txt", "a /b.txt", "a.txt "):
            with self.subTest(path=path):
                with self.assertRaises(VpkError):
                    canonicalize_virtual_path(path)

    def test_non_utf8_names_are_preserved_losslessly_with_explicit_count(self):
        data = build_vpk().replace(b"scripts", b"script\xff", 1)
        result = self.parse(data)
        self.assertEqual(result.non_utf8_paths, 1)
        self.assertEqual(result.assets[0].original_path_bytes, b"script\xff/fixture.txt")
        self.assertEqual(result.assets[0].canonical_path_bytes, b"script\xff/fixture.txt")
        self.assertEqual(result.assets[0].original_path.encode("utf-8", errors="surrogateescape"), result.assets[0].original_path_bytes)

    def test_unterminated_tree_is_rejected(self):
        self.assert_error(struct.pack("<III", 0x55AA1234, 1, 4) + b"abcd", "INVALID_TREE_STRING")

    def test_truncated_entry_preload_and_trailing_tree(self):
        def archive(tree):
            return struct.pack("<III", 0x55AA1234, 1, len(tree)) + tree
        prefix = b"txt\0scripts\0name\0"
        self.assert_error(archive(prefix + b"short"), "TRUNCATED_ENTRY")
        fields = struct.pack("<IHHIIH", 0, 50, 0x7FFF, 0, 0, 0xFFFF)
        self.assert_error(archive(prefix + fields + b"x"), "TRUNCATED_PRELOAD")
        self.assert_error(archive(b"\0trailing"), "TRAILING_TREE_DATA")

    def test_resource_limits_must_be_positive(self):
        for kwargs in ({"max_tree_bytes": 0}, {"max_entries": -1}, {"max_path_bytes": 0}):
            with self.assertRaises(ValueError):
                ParserLimits(**kwargs)
