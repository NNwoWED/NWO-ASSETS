"""Generated miniature assets only: no reads or writes to the project baseline."""
from pathlib import Path
import csv
from dataclasses import replace
import struct
import tempfile
import unittest
from unittest.mock import patch

from nwoassets.errors import FormatError
from nwoassets.exporter import compose_appearance_sheet
from nwoassets.importer import import_items, prepare_preserved_appearance, read_manifest
from nwoassets.otb import OtbNode, parse_otb_tree
from nwoassets.otfi import OtfiConfig
from nwoassets.pipeline import validate_root
from nwoassets.png import PngImage, write_png_rgba
from nwoassets.roundtrip import (
    encode_item_appearance, read_dat_animation_timings,
    scan_dat_record_spans, write_otb_document,
)
from nwoassets.sprites import decode_sprite_rgba, encode_sprite_rgba, read_spr_blocks, sprite_hash
from nwoassets.versioning import find_rar


OTFI = OtfiConfig(True, True, True, True, 'Tibia.dat', 'Tibia.spr', 32, 4096)


try:
    find_rar()
    HAS_RAR = True
except FormatError:
    HAS_RAR = False
requires_rar = unittest.skipUnless(HAS_RAR, 'rar.exe required for generated fixture integration')


def tile(index):
    return bytes((index * 3, 70, 120, 255)) * 1024


def manifest(root, **extra):
    path = root / 'manifest.csv'
    values = {'sequence': 1, 'client_id': 100, 'source_path': 'water.png', 'preserve_layout': 1}
    values.update(extra)
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(values))
        writer.writeheader()
        writer.writerow(values)
    return path


def fixture(root, *, frames=3, width=1, height=1, layers=2, px=2, py=2, pz=2):
    for name in ('860', 'items', 'world'):
        (root / 'assets' / name).mkdir(parents=True)
    n = width * height * layers * px * py * pz * frames
    assert n <= 80
    ids = tuple(range(1, n + 1))
    appearance = bytearray(encode_item_appearance(
        width, height, frames, ids, OTFI, layers=layers,
        pattern_x=px, pattern_y=py, pattern_z=pz,
        exact_size=47 if width > 1 or height > 1 else None,
        frame_duration_ms=100 if frames > 1 else None, animation_async=frames > 1,
    ))
    if frames > 1:
        animation = 7 + (1 if width > 1 or height > 1 else 0)
        struct.pack_into('<iB', appearance, animation + 1, -1, 2)
        for frame in range(frames):
            struct.pack_into('<II', appearance, animation + 6 + frame * 8, 80 + frame, 140 + frame)
    plain = encode_item_appearance(1, 1, 1, (1,), OTFI)
    # Ground speed, blocking and light payload must all survive unchanged.
    properties = b'\0' + struct.pack('<H', 220) + b'\x0D\x15' + struct.pack('<HH', 7, 215) + b'\xFF'
    data = (struct.pack('<IHHHH', 0x4C2C7993, 101, 1, 1, 1) + properties + appearance
            + b'\xFF' + plain + b'\xFF\x01\0' + plain + (b'\xFF' + plain) * 2)
    dat = root / 'assets/860/Tibia.dat'
    dat.write_bytes(data)
    blocks = [encode_sprite_rgba(tile(i)) for i in ids]
    body = bytearray()
    offsets = []
    for block in blocks:
        offsets.append(8 + 4 * n + len(body))
        body.extend(block)
    spr = root / 'assets/860/Tibia.spr'
    spr.write_bytes(struct.pack('<II', 0x4C220594, n) + struct.pack('<' + 'I' * n, *offsets) + body)
    (root / 'assets/860/Tibia.otfi').write_text(
        'DatSpr\n  extended: true\n  transparency: true\n  frame-durations: true\n'
        '  frame-groups: true\n  metadata-file: Tibia.dat\n  sprites-file: Tibia.spr\n'
        '  sprite-size: 32\n  sprite-data-size: 4096\n', encoding='utf-8')
    flags = 1 | (1 << 24) | (1 << 27)

    def node(sid, cid, digest):
        data = bytearray(b'\x01' + struct.pack('<I', flags))
        for key, value in ((0x10, struct.pack('<H', sid)), (0x11, struct.pack('<H', cid)),
                           (0x20, digest), (0x21, struct.pack('<H', 75))):
            data.extend(bytes((key,)) + struct.pack('<H', len(value)) + value)
        return OtbNode(bytes(data), [])

    digest = sprite_hash([tile(i) for i in ids[:width * height * layers]])
    otb = root / 'assets/items/items.otb'
    header = b'\0' + struct.pack('<IBHIII', 0, 1, 140, 3, 20, 20) + b'8.60'.ljust(128, b'\0')
    write_otb_document(0, OtbNode(header, [node(100, 100, digest), node(101, 100, digest),
                                         node(102, 101, sprite_hash([tile(1)]))]), otb)
    (root / 'assets/items/items.xml').write_text('<items><item fromid="100" toid="102" name="water"/></items>', encoding='utf-8')
    world = root / 'assets/world/mapanovo.otbm'
    write_otb_document(0, OtbNode(b'\0' + struct.pack('<IHHII', 2, 512, 512, 3, 20),
                                [OtbNode(b'\x02', [])]), world)
    span = scan_dat_record_spans(data, OTFI, str(dat))[0]
    # New pixels retain the same layout but differ in every nonempty sprite.
    new_tiles = {i: bytes((120, i * 3, 70, 255)) * 1024 for i in ids}
    image = compose_appearance_sheet(span.appearances[0], new_tiles)
    write_png_rgba(root / 'water.png', image)
    return {'dat': dat, 'spr': spr, 'otb': otb, 'world': world}, span, tuple(new_tiles.values())


class PreserveLayoutTests(unittest.TestCase):
    @requires_rar
    def test_existing_vertical_animation_import_remains_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, _, _ = fixture(root, frames=1, layers=1, px=1, py=1, pz=1)
            write_png_rgba(root / 'water.png', PngImage(32, 64, tile(10) + tile(20)))
            report = import_items(root, manifest(root, preserve_layout=0, frames=2,
                                                frame_duration_ms=100, animation_async=1), deep_spr=True)
            data = paths['dat'].read_bytes()
            appearance = scan_dat_record_spans(data, OTFI, 'standard-import')[0].appearances[0]
            self.assertEqual((appearance.width, appearance.height, appearance.layers,
                              appearance.pattern_x, appearance.pattern_y, appearance.pattern_z,
                              appearance.frames), (1, 1, 1, 1, 1, 1, 2))
            timing = read_dat_animation_timings(data, OTFI, 'items', {100}, 'standard')[100]
            self.assertEqual(timing.durations, ((100, 100), (100, 100)))
            self.assertTrue(timing.animation_async)
            self.assertEqual(report['layout_preserved_client_ids'], [])

    def test_transparent_pattern_and_inconsistent_sprite_array(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, span, _ = fixture(root)
            data = bytearray(paths['dat'].read_bytes())
            struct.pack_into('<I', data, span.end - 4, 0)
            source = bytes(data)
            span = scan_dat_record_spans(source, OTFI, 'with-empty-pattern')[0]
            appearance = span.appearances[0]
            pixels = {i: tile(i) for i in appearance.sprite_ids}
            pixels[0] = bytes(4096)
            write_png_rgba(root / 'water.png', compose_appearance_sheet(appearance, pixels))
            entry = read_manifest(manifest(root))[0]
            with self.assertRaisesRegex(FormatError, 'Client ID diverge'):
                prepare_preserved_appearance(replace(entry, client_id=101), source, span, OTFI, 1000)
            _, tiles, ids, encoded = prepare_preserved_appearance(entry, source, span, OTFI, 1000)
            self.assertEqual(tiles[-1], bytes(4096))
            self.assertEqual(ids[-1], 1000 + len(tiles) - 1)
            self.assertEqual(encoded[:-len(ids) * 4], source[span.properties_end:span.end - len(ids) * 4])
            corrupt = source[:span.end - 1] + b'\x01' + source[span.end:]
            with self.assertRaisesRegex(FormatError, 'array de sprites DAT inconsistente'):
                prepare_preserved_appearance(entry, corrupt, span, OTFI, 1000)

    @requires_rar
    def test_import_roundtrips_every_axis_variable_timing_and_shared_otb_nodes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, original_span, expected_tiles = fixture(root)
            before = {key: path.read_bytes() for key, path in paths.items()}
            self.assertTrue(validate_root(root, deep_spr=True)['passed'])
            report = import_items(root, manifest(root), deep_spr=True)
            after = paths['dat'].read_bytes()
            spans = scan_dat_record_spans(after, OTFI, str(paths['dat']))
            n = len(expected_tiles)
            original_ids = original_span.appearances[0].sprite_ids
            self.assertEqual(spans[0].appearances[0].sprite_ids, tuple(range(n + 1, n * 2 + 1)))
            self.assertEqual(before['dat'][:original_span.end - n * 4], after[:spans[0].end - n * 4])
            self.assertEqual(before['dat'][original_span.end:], after[spans[0].end:])
            self.assertEqual(paths['world'].read_bytes(), before['world'])
            old_timings = read_dat_animation_timings(before['dat'], OTFI, 'items', {100}, 'old')[100]
            new_timings = read_dat_animation_timings(after, OTFI, 'items', {100}, 'new')[100]
            self.assertEqual(old_timings, new_timings)
            self.assertEqual(new_timings.loop_count, -1)
            self.assertEqual(new_timings.start_frame, 2)
            self.assertEqual(new_timings.durations, ((80, 140), (81, 141), (82, 142)))
            new_ids = spans[0].appearances[0].sprite_ids
            blocks = read_spr_blocks(paths['spr'], set(new_ids), OTFI)
            self.assertEqual(tuple(decode_sprite_rgba(blocks[i], transparency=True) for i in new_ids), expected_tiles)
            old_blocks = read_spr_blocks(paths['spr'], set(original_ids), OTFI)
            self.assertEqual(tuple(decode_sprite_rgba(old_blocks[i], transparency=True) for i in original_ids), tuple(tile(i) for i in original_ids))
            source_otb = root / 'source-check.otb'
            source_otb.write_bytes(before['otb'])
            _, old_root = parse_otb_tree(source_otb)
            _, new_root = parse_otb_tree(paths['otb'])
            expected_hash = sprite_hash(expected_tiles[:2])
            self.assertEqual(new_root.data, old_root.data)
            for index in (0, 1):
                self.assertEqual(new_root.children[index].data,
                                 old_root.children[index].data.replace(sprite_hash([tile(1), tile(2)]), expected_hash))
            self.assertEqual(new_root.children[2].data, old_root.children[2].data)
            self.assertTrue(report['transaction_committed'])
            self.assertTrue(report['final_validation_passed'])
            self.assertEqual(report['layout_preserved_client_ids'], [100])
            self.assertEqual(report['otb_nodes_updated'], {100: 2})
            self.assertEqual(report['items'][0]['frames'], 3)
            self.assertEqual(report['items'][0]['pattern_z'], 2)
            version = Path(report['version_backup']['root'])
            self.assertTrue(all((version / name).is_file() for name in ('860.rar', 'items.rar', 'world.zip', 'version.json')))

    @requires_rar
    def test_static_multitile_preserves_exact_size_and_existing_otb_animation_bit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, span, expected = fixture(root, frames=1, width=2, height=2, layers=1, px=1, py=1, pz=1)
            before = paths['dat'].read_bytes()
            report = import_items(root, manifest(root), deep_spr=True)
            written = scan_dat_record_spans(paths['dat'].read_bytes(), OTFI, 'new')[0]
            self.assertEqual(written.appearances[0].exact_size, 47)
            self.assertEqual(written.appearances[0].frames, 1)
            self.assertEqual(report['items'][0]['layers'], 1)
            self.assertEqual(before[:span.end - len(expected) * 4], paths['dat'].read_bytes()[:written.end - len(expected) * 4])
            _, otb = parse_otb_tree(paths['otb'])
            self.assertTrue(struct.unpack_from('<I', otb.children[0].data, 1)[0] & (1 << 24))

    def test_wrong_sheet_dimensions_abort_before_version_or_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, _, _ = fixture(root)
            before = {key: path.read_bytes() for key, path in paths.items()}
            write_png_rgba(root / 'water.png', PngImage(32, 32, bytes(4096)))
            with patch('nwoassets.importer.create_version') as version:
                with self.assertRaisesRegex(FormatError, 'layout exige'):
                    import_items(root, manifest(root), deep_spr=True)
                version.assert_not_called()
            self.assertEqual(before, {key: path.read_bytes() for key, path in paths.items()})

    def test_version_failure_prevents_any_pending_binary_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, _, _ = fixture(root)
            before = {key: path.read_bytes() for key, path in paths.items()}
            with patch('nwoassets.importer.create_version', side_effect=FormatError('archive rejected')):
                with patch('nwoassets.importer.append_spr_blocks') as append:
                    with self.assertRaisesRegex(FormatError, 'archive rejected'):
                        import_items(root, manifest(root), deep_spr=True)
                    append.assert_not_called()
            self.assertEqual(before, {key: path.read_bytes() for key, path in paths.items()})

    @requires_rar
    def test_final_validation_failure_restores_all_generated_binaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, _, _ = fixture(root)
            before = {key: path.read_bytes() for key, path in paths.items()}
            with patch('nwoassets.importer.validate_root', return_value={'passed': False, 'errors': ['forced failure'], 'warnings': []}):
                with self.assertRaises(FormatError):
                    import_items(root, manifest(root), deep_spr=True)
            self.assertEqual(before, {key: path.read_bytes() for key, path in paths.items()})
            self.assertEqual(list(root.rglob('*.nwoassets.*')), [])

    def test_preserve_manifest_rejects_animation_changes_and_invalid_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_png_rgba(root / 'water.png', PngImage(32, 32, bytes(4096)))
            self.assertTrue(read_manifest(manifest(root))[0].preserve_layout)
            for extra in ({'frames': 3}, {'frame_duration_ms': 100}, {'animation_async': 0}, {'preserve_layout': 'yes'}):
                with self.subTest(extra=extra), self.assertRaises(FormatError):
                    read_manifest(manifest(root, **extra))


if __name__ == '__main__':
    unittest.main()
