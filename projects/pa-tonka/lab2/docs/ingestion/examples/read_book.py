"""Documentation example: inspect one standalone book using only Python stdlib."""

import argparse
import hashlib
import json
from pathlib import Path


def embedded(node):
    if isinstance(node, dict):
        if node.get("kind") == "embedded_entity":
            yield node
        else:
            for child in node.values():
                yield from embedded(child)
    elif isinstance(node, list):
        for child in node:
            yield from embedded(child)


def inspect(directory, book_id, chapter_index=None):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    meta = manifest["books"][book_id]
    raw = (directory / meta["path"]).read_bytes()
    if len(raw) != meta["bytes"] or hashlib.sha256(raw).hexdigest() != meta["file_sha256"]:
        raise ValueError("Book size/file_sha256 differs from manifest")
    book = json.loads(raw)
    if book["book"]["id"] != book_id:
        raise ValueError("Requested book ID differs from payload")

    occurrences = {
        item["occurrence_id"]: item
        for chapter in book["chapters"]
        for item in embedded(chapter["content"])
    }
    entities = {item["entity_id"]: item for item in book["domain"]["entities"]}

    def payload(entity):
        if entity["representation"] == "book_insertion":
            return occurrences[entity["occurrence_id"]]["data"]
        return entity["data"]

    if chapter_index is None:
        chapter = next(ch for ch in book["chapters"] if next(embedded(ch["content"]), None))
    else:
        if not 0 <= chapter_index < len(book["chapters"]):
            raise ValueError("Chapter index is outside this book")
        chapter = book["chapters"][chapter_index]
    first = next(embedded(chapter["content"]), None)
    result = {
        "book": book_id,
        "title": book["book"]["title"],
        "chapter": {"index": chapter["chapter_index"], "title": chapter["title"], "origin": chapter["origin"]},
        "embedded": None if first is None else {
            "entity_id": first["entity_id"],
            "name": first["data"].get("name"),
            "placement": first["placement"],
            "entity_origin": first["entity_origin"],
        },
    }
    if book_id == "XPHB":
        barbarian = next(
            entity for entity in entities.values()
            if entity["prop"] == "class"
            and payload(entity)["name"] == "Barbarian"
            and payload(entity)["source"] == "XPHB"
        )
        subclasses = [
            payload(entities[edge["to_entity_id"]])["name"]
            for edge in book["domain"]["relationships"]
            if edge["from_entity_id"] == barbarian["entity_id"] and edge["relation"] == "subclass"
        ]
        result["barbarian"] = {
            "class_table_groups": len(payload(barbarian).get("classTableGroups", [])),
            "subclasses": subclasses,
        }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Explicit build directory containing manifest.json")
    parser.add_argument("--book", choices=["XPHB", "XDMG", "XMM"], default="XPHB")
    parser.add_argument("--chapter", type=int, help="Zero-based index; default: first chapter with an insertion")
    args = parser.parse_args()
    print(json.dumps(inspect(args.directory, args.book, args.chapter), ensure_ascii=False, indent=2))
