import json
from pathlib import Path
import subprocess
import sys

import pytest

from tools.pack_catalog import CATALOG_FORMAT, installed_pack_registry, pack_catalog, write_catalog


def write_pack(path: Path, *, pack_id: str = "unskinned", title: str = "Unskinned") -> None:
    path.write_text(json.dumps({
        "format": "prepflow_pack", "version": "1.0", "pack_id": pack_id,
        "title": title,
        "questions": [{
            "id": f"PFQ-{pack_id}-000000001", "chapter": 1,
            "chapter_title": "Growth", "type": "multiple_choice", "stem": "Which?",
            "choices": [{"label": "A", "text": "First"}],
            "correct_answers": ["A"], "rationale": "Because.",
        }],
    }), encoding="utf-8")


def test_catalog_includes_valid_unstyled_pack_with_dynamic_metadata(tmp_path: Path) -> None:
    packs = tmp_path / "packs"; packs.mkdir()
    write_pack(packs / "unskinned.prepflow.json")

    catalog = pack_catalog(packs)

    assert catalog["format"] == CATALOG_FORMAT
    assert catalog["books"] == [{
        "id": "unskinned", "title": "Unskinned",
        "path": "../packs/unskinned.prepflow.json",
        "question_count": 1, "chapter_count": 1,
    }]


def test_catalog_decorates_pediatrics_with_canonical_book_art(tmp_path: Path) -> None:
    packs = tmp_path / "packs"; packs.mkdir()
    write_pack(packs / "pediatrics.prepflow.json", pack_id="pediatrics", title="Pediatrics")

    book = pack_catalog(packs)["books"][0]

    assert book["theme"] == "pediatrics"
    assert book["shelf_label"] == "Pediatrics"
    assert book["art"].startswith("images/quiz-builder/books/pediatrics-closed.png")


def test_installed_registry_discovers_valid_packs_by_pack_id(tmp_path: Path) -> None:
    packs = tmp_path / "packs"; packs.mkdir()
    path = packs / "new-book.prepflow.json"
    write_pack(path, pack_id="new_book", title="New Book")

    assert installed_pack_registry(packs) == {"new_book": path}


def test_catalog_write_is_metadata_only_and_rejects_invalid_installed_pack(tmp_path: Path) -> None:
    packs = tmp_path / "packs"; packs.mkdir()
    write_pack(packs / "valid.prepflow.json", pack_id="valid")
    destination = tmp_path / "web" / "data" / "pack-catalog.json"
    assert write_catalog(packs, destination) == destination
    assert json.loads(destination.read_text(encoding="utf-8"))["books"][0]["id"] == "valid"
    precache = (tmp_path / "web" / "pack-precache.js").read_text(encoding="utf-8")
    assert "../packs/valid.prepflow.json" in precache

    (packs / "broken.prepflow.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid installed Pack"):
        pack_catalog(packs)


def test_catalog_write_refreshes_pack_cache_for_question_only_repair(tmp_path: Path) -> None:
    packs = tmp_path / "packs"; packs.mkdir()
    pack = packs / "unskinned.prepflow.json"
    write_pack(pack)
    destination = tmp_path / "web" / "data" / "pack-catalog.json"

    write_catalog(packs, destination)
    before_catalog = destination.read_text(encoding="utf-8")
    before_precache = (tmp_path / "web" / "pack-precache.js").read_text(encoding="utf-8")

    repaired = json.loads(pack.read_text(encoding="utf-8"))
    repaired["questions"][0]["stem"] = "Corrected question?"
    pack.write_text(json.dumps(repaired), encoding="utf-8")
    write_catalog(packs, destination)

    assert destination.read_text(encoding="utf-8") == before_catalog
    assert (tmp_path / "web" / "pack-precache.js").read_text(encoding="utf-8") != before_precache


def test_installer_adds_pack_and_catalog_entry_without_book_specific_ui(tmp_path: Path) -> None:
    source = tmp_path / "unskinned.prepflow.json"
    write_pack(source)
    packs = tmp_path / "installed"; catalog = tmp_path / "web" / "data" / "pack-catalog.json"

    subprocess.run([
        sys.executable, "tools/install_pack.py", str(source),
        "--packs", str(packs), "--catalog", str(catalog),
    ], check=True)

    assert (packs / source.name).is_file()
    assert json.loads(catalog.read_text(encoding="utf-8"))["books"][0]["id"] == "unskinned"
