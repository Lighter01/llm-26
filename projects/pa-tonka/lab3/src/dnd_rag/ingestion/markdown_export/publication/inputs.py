"""Read only the manifest and books of one explicitly selected build."""

import hashlib
import re
from pathlib import Path

from ..common.json_io import strict_json
from ..common.model import BOOK_IDS, ExportError, require


def read_build(directory: str | Path) -> tuple[dict, ...]:
    try:
        directory = Path(directory).resolve(strict=True)
        manifest_path = directory / 'manifest.json'
        require(
            manifest_path.is_file() and not manifest_path.is_symlink(),
            'INVALID_BUILD',
            'Expected a regular manifest.json inside the selected build',
            directory=str(directory),
        )
        manifest = strict_json(manifest_path.read_bytes())
        require(isinstance(manifest, dict), 'INVALID_BUILD', 'Manifest must be an object')
        require(
            manifest.get('manifest_version') == '2.0.0',
            'UNSUPPORTED_MANIFEST',
            str(manifest.get('manifest_version')),
        )
        require(
            manifest.get('schema', {}).get('version') == '1.0.0',
            'UNSUPPORTED_SCHEMA',
            str(manifest.get('schema')),
        )
        require(
            manifest.get('validation', {}).get('status') == 'PASS',
            'FAILED_INPUT_BUILD',
            'Manifest has no successful validation',
        )
        require(
            isinstance(manifest.get('books'), dict) and set(manifest['books']) == set(BOOK_IDS),
            'BOOK_SET',
            'Expected the three core books',
        )
        upstream = manifest.get('upstream')
        require(
            isinstance(upstream, dict)
            and isinstance(upstream.get('checkout_sha'), str)
            and re.fullmatch('[0-9a-f]{40}', upstream['checkout_sha']),
            'INVALID_BUILD',
            'Invalid upstream checkout SHA',
        )
        result = []
        seen = set()
        for book_id, metadata in manifest['books'].items():
            require(
                isinstance(metadata, dict)
                and isinstance(metadata.get('path'), str)
                and bool(metadata['path']),
                'INPUT_PATH',
                'Expected a manifest-relative book path',
                book=book_id,
            )
            relative = Path(metadata['path'])
            require(
                not relative.is_absolute() and '..' not in relative.parts,
                'INPUT_PATH',
                'Book path must stay inside the selected build',
                book=book_id,
            )
            path = (directory / relative).resolve(strict=True)
            require(
                path.is_relative_to(directory) and path.is_file(),
                'INPUT_PATH',
                'Book path escapes build',
                book=book_id,
            )
            require(
                path not in seen and path != manifest_path,
                'INPUT_PATH',
                'Book paths must be distinct',
                book=book_id,
            )
            seen.add(path)
            require(
                type(metadata.get('bytes')) is int
                and metadata['bytes'] > 0
                and isinstance(metadata.get('file_sha256'), str)
                and re.fullmatch('[0-9a-f]{64}', metadata['file_sha256']),
                'INPUT_INTEGRITY',
                'Invalid declared size or SHA-256',
                book=book_id,
            )
            require(
                path.stat().st_size == metadata['bytes'],
                'INPUT_INTEGRITY',
                'Size differs from manifest',
                book=book_id,
            )
            raw = path.read_bytes()
            require(
                len(raw) == metadata['bytes']
                and hashlib.sha256(raw).hexdigest() == metadata['file_sha256'],
                'INPUT_INTEGRITY',
                'Size or file SHA-256 differs from manifest',
                book=book_id,
            )
            book = strict_json(raw)
            require(
                book['book']['id'] == book_id
                and book['schema_version'] == manifest['schema']['version'],
                'INPUT_IDENTITY',
                'Book ID/schema differs from manifest',
                book=book_id,
            )
            require(
                book['upstream'] == manifest['upstream'],
                'MIXED_SNAPSHOT',
                'Book snapshot differs from manifest',
                book=book_id,
            )
            result.append(book)
        return tuple(result)
    except ExportError:
        raise
    except (OSError, KeyError, TypeError, AttributeError, ValueError, RecursionError) as error:
        raise ExportError('INVALID_BUILD', str(error), directory=str(directory)) from error
